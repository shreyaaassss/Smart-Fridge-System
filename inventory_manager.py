import re
import pymongo
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from database import DatabaseStateMachine, DatabaseConnectionContext
from vision_service import VisionService
from user_profile import UserProfileManager
from utils import log_error, safe_db_call

class InventoryManager:
    """Manages fridge inventory operations with differential updates, behavioral learning, and grocery list management."""
    
    def __init__(self, database: DatabaseStateMachine, vision_service: VisionService, user_mgr: UserProfileManager):
        self.database = database
        self.vision_service = vision_service
        self.user_mgr = user_mgr
        self.consumption_patterns = {}  # Stores learned consumption patterns
        self.current_grocery_list = {
            "smart_recommendations": [],
            "selected_items": [],
            "custom_items": []
        }

    # ----------------- Inventory Management Methods -----------------

    def _compute_inventory_diff(self, old_inventory: List[Dict], new_inventory: List[Dict]) -> Dict:
        """Compute the difference between old and new inventories."""
        diff = {
            'added': [],
            'removed': [],
            'changed': [],
            'unchanged': []
        }
        
        # Create normalized dictionaries for comparison
        old_items = {(item['name'].lower(), item['category'].lower()): item for item in old_inventory}
        new_items = {(item['name'].lower(), item['category'].lower()): item for item in new_inventory}
        
        # Find added items
        for key in set(new_items.keys()) - set(old_items.keys()):
            diff['added'].append(new_items[key])
        
        # Find removed items
        for key in set(old_items.keys()) - set(new_items.keys()):
            diff['removed'].append(old_items[key])
        
        # Compare quantities of existing items
        for key in set(old_items.keys()) & set(new_items.keys()):
            old_item = old_items[key]
            new_item = new_items[key]
            
            # Try to extract numerical quantities if possible
            old_qty = self._extract_quantity(old_item.get('quantity', '1'))
            new_qty = self._extract_quantity(new_item.get('quantity', '1'))
            
            if old_qty != new_qty:
                changed_item = new_item.copy()
                changed_item['quantity_diff'] = new_qty - old_qty
                diff['changed'].append(changed_item)
            else:
                diff['unchanged'].append(new_item)
        
        return diff

    def _extract_quantity(self, quantity_str: str) -> float:
        """Extract numerical quantity from string (e.g., '2 bottles' -> 2.0)."""
        if not quantity_str:
            return 1.0
            
        try:
            # Extract first number from string
            match = re.search(r'(\d+\.?\d*)', str(quantity_str))
            return float(match.group(1)) if match else 1.0
        except:
            return 1.0
            
    def _update_consumption_patterns(self, diff: Dict) -> None:
        """Update consumption patterns based on inventory differences."""
        timestamp = datetime.now()
        
        # Track removed items as consumed
        for item in diff['removed']:
            item_name = item['name'].lower()
            if item_name not in self.consumption_patterns:
                self.consumption_patterns[item_name] = {
                    'last_consumed': timestamp,
                    'consumption_rate': 0,
                    'history': []
                }
            
            # Update consumption history
            self.consumption_patterns[item_name]['history'].append({
                'timestamp': timestamp,
                'action': 'consumed',
                'quantity': item.get('quantity', '1')
            })
            self.consumption_patterns[item_name]['last_consumed'] = timestamp
        
        # Track quantity changes
        for item in diff['changed']:
            if item['quantity_diff'] < 0:  # Only track reductions
                item_name = item['name'].lower()
                if item_name not in self.consumption_patterns:
                    self.consumption_patterns[item_name] = {
                        'last_consumed': timestamp,
                        'consumption_rate': 0,
                        'history': []
                    }
                
                consumed_qty = abs(item['quantity_diff'])
                self.consumption_patterns[item_name]['history'].append({
                    'timestamp': timestamp,
                    'action': 'partial_consumed',
                    'quantity': consumed_qty
                })
                self.consumption_patterns[item_name]['last_consumed'] = timestamp
        
        # Calculate consumption rates
        for item_name, pattern in self.consumption_patterns.items():
            if len(pattern['history']) >= 2:
                # Calculate average time between consumptions
                time_diffs = []
                for i in range(1, len(pattern['history'])):
                    delta = (pattern['history'][i]['timestamp'] - 
                            pattern['history'][i-1]['timestamp']).total_seconds()
                    if delta > 0:  # Only include positive time differences
                        time_diffs.append(delta)
                
                if time_diffs:  # Only calculate if we have valid time differences
                    avg_hours_between = sum(time_diffs) / len(time_diffs) / 3600
                    if avg_hours_between > 0:  # Prevent division by zero
                        pattern['consumption_rate'] = 24 / avg_hours_between  # Items per day

    def save_items(self, new_items: List[Dict]) -> Dict[str, int]:
        """Save inventory items with differential updates and behavioral tracking."""
        if not new_items:
            return {"inserted": 0, "updated": 0, "removed": 0}
        
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                if not self.user_mgr.current_user:
                    print("\nNo user logged in")
                    return {"inserted": 0, "updated": 0, "removed": 0}
                
                username = self.user_mgr.current_user['username']
                timestamp = datetime.now()
                
                # Get previous inventory
                old_inventory = self.get_current_inventory()
                
                # Compute differences
                diff = self._compute_inventory_diff(old_inventory, new_items)
                self._update_consumption_patterns(diff)
                
                # Update database
                result = {"inserted": 0, "updated": 0, "removed": 0}
                
                # Handle added items
                for item in diff['added']:
                    # Create safe regex pattern by escaping and anchoring
                    name_pattern = f"^{re.escape(item['name'].strip())}$"
                    category_pattern = f"^{re.escape(item['category'].strip())}$"
                    
                    # Check if item already exists (case-insensitive)
                    existing_item = db['users'].find_one({
                        "username": username,
                        "inventory.name": {"$regex": name_pattern, "$options": "i"},
                        "inventory.category": {"$regex": category_pattern, "$options": "i"}
                    })
                    
                    if existing_item:
                        # Update existing item
                        update_result = db['users'].update_one(
                            {
                                "username": username,
                                "inventory.name": {"$regex": name_pattern, "$options": "i"},
                                "inventory.category": {"$regex": category_pattern, "$options": "i"}
                            },
                            {
                                "$set": {
                                    "inventory.$.quantity": item.get('quantity', 1),
                                    "inventory.$.notes": item.get('notes', ''),
                                    "inventory.$.last_seen": timestamp
                                }
                            }
                        )
                        if update_result.modified_count > 0:
                            result["updated"] += 1
                    else:
                        # Insert new item - use $addToSet to prevent duplicates
                        db['users'].update_one(
                            {"username": username},
                            {
                                "$addToSet": {
                                    "inventory": {
                                        "name": item['name'],
                                        "category": item['category'],
                                        "quantity": item.get('quantity', 1),
                                        "notes": item.get('notes', ''),
                                        "last_seen": timestamp
                                    }
                                }
                            }
                        )
                        result["inserted"] += 1
                
                # Handle removed items
                for item in diff['removed']:
                    # Use exact match for removal (case-sensitive)
                    delete_result = db['users'].update_one(
                        {"username": username},
                        {
                            "$pull": {
                                "inventory": {
                                    "name": item['name'],
                                    "category": item['category']
                                }
                            },
                            "$push": {
                                "consumption_history": {
                                    "item_name": item['name'],
                                    "category": item['category'],
                                    "action": "consumed",
                                    "timestamp": timestamp
                                }
                            }
                        }
                    )
                    if delete_result.modified_count > 0:
                        result["removed"] += 1
                
                # Handle quantity changes with error handling
                for item in diff['changed']:
                    try:
                        if item['quantity_diff'] < 0:  # Only track reductions
                            item_name = item['name'].lower()
                            if item_name not in self.consumption_patterns:
                                self.consumption_patterns[item_name] = {
                                    'last_consumed': timestamp,
                                    'consumption_rate': 0,
                                    'history': []
                                }
                            
                            consumed_qty = abs(item['quantity_diff'])
                            self.consumption_patterns[item_name]['history'].append({
                                'timestamp': timestamp,
                                'action': 'partial_consumed',
                                'quantity': consumed_qty
                            })
                            self.consumption_patterns[item_name]['last_consumed'] = timestamp
                    except Exception as e:
                        log_error("quantity change tracking", e)
                        continue
                
                return result
                
        except pymongo.errors.OperationFailure as e:
            log_error("Database operation failed during inventory save", e)
            return {"inserted": 0, "updated": 0, "removed": 0}
        except Exception as e:
            log_error("Unexpected error during inventory save", e)
            return {"inserted": 0, "updated": 0, "removed": 0}

    def get_current_inventory(self) -> List[Dict]:
        """Retrieve current inventory from database."""
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                if not self.user_mgr.current_user:
                    return []
                
                username = self.user_mgr.current_user['username']
                
                # Get user document
                user = db['users'].find_one({"username": username})
                if not user:
                    return []
                
                # Get items seen in the last 7 days (consider them still in fridge)
                one_week_ago = datetime.now() - timedelta(days=7)
                inventory = user.get('inventory', [])
                current_items = [item for item in inventory
                               if item.get('last_seen', datetime.now()) >= one_week_ago]
                
                # Sort by category and name
                sorted_items = sorted(
                    current_items,
                    key=lambda x: (x.get('category', ''), x.get('name', ''))
                )

                return sorted_items
        except Exception as e:
            log_error("inventory fetch", e)
            return []

    def display_inventory(self) -> None:
        """Display current inventory in a formatted table."""
        items = self.get_current_inventory()
        
        if not items:
            print("\nNo items in inventory or database unavailable")
            return
        
        # Group items by category
        categories = {}
        for item in items:
            cat = item.get('category', 'Uncategorized')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)
        
        # Display inventory
        print("\nCurrent Refrigerator Inventory:")
        print("=" * 50)
        
        for category, items in categories.items():
            print(f"\n{category.upper()}:")
            print("-" * len(category))
            
            for item in items:
                name = item.get('name', 'Unknown')
                quantity = str(item.get('quantity', ''))  # Convert quantity to string
                last_seen = item.get('last_seen', datetime.now())
                last_seen_str = last_seen.strftime("%Y-%m-%d") if isinstance(last_seen, datetime) else str(last_seen)
                notes = item.get('notes', '')
                
                # Check for allergy risks if user is logged in
                if self.user_mgr.current_user:
                    user_allergies = self.user_mgr.current_profile.get('allergies', [])
                    if user_allergies and self.vision_service.check_allergy_risk(name, user_allergies):
                        name = f"⚠️ {name}"
                
                print(f"  {name.ljust(25)} {quantity.ljust(15)} {last_seen_str.ljust(15)} {notes}")

    def scan_fridge(self, camera_service) -> bool:
        """Scan fridge contents using camera and AI analysis."""
        print("\nScanning Fridge Contents")
       
        # Capture image
        print("\nInitiating camera capture...")
        capture_result = camera_service.capture_image()
       
        if not capture_result:
            print("\nFailed to capture image")
            return False
       
        # Get latest image
        print("\nRetrieving latest image...")
        image_path = camera_service.get_latest_image()
       
        if not image_path:
            print("\nFailed to retrieve image")
            return False
           
        # Process image
        print("\nProcessing image for analysis...")
        processed_image = camera_service.preprocess_image(image_path)
       
        # Analyze inventory with AI
        print("\nAnalyzing image with AI vision...")
        inventory_text = self.vision_service.analyze_inventory(processed_image)
       
        if not inventory_text:
            print("\nFailed to analyze image")
            return False
           
        # Parse detected items
        print("\nProcessing detected items...")
        items = self.vision_service.parse_inventory(inventory_text)
       
        # Save to database
        print("\nSaving inventory to database...")
        result = self.save_items(items)
       
        print(f"\nScan complete! Added {result['inserted']} new items, updated {result['updated']} items, and removed {result['removed']} items.")
       
        # Display detected items
        print("\nDetected Items:")
        print(inventory_text)
       
        return True

    def remove_item(self) -> None:
        """Remove an item from inventory."""
        items = self.get_current_inventory()
       
        if not items:
            print("\nNo items in inventory")
            return
       
        # Display items
        print("\nRemove Item from Inventory")
        print("Select an item to remove:")
       
        for i, item in enumerate(items, 1):
            print(f"{i}. {item.get('name', 'Unknown')} ({item.get('category', 'Uncategorized')})")
        print("0. Cancel")
       
        try:
            choice = int(input("\nEnter item number: "))
            if choice == 0:
                return
               
            if 1 <= choice <= len(items):
                selected_item = items[choice-1]
               
                with DatabaseConnectionContext(self.database.get_client()) as db:
                    # Remove from user's inventory
                    username = self.user_mgr.current_user['username']
                    db['users'].update_one(
                        {"username": username},
                        {"$pull": {"inventory": {"name": selected_item['name'], "category": selected_item['category']}}}
                    )
                   
                    # Log the removal
                    db['session_logs'].insert_one({
                        "action": "item_removed",
                        "timestamp": datetime.now(),
                        "username": username,
                        "item_name": selected_item.get('name', 'Unknown'),
                        "category": selected_item.get('category', 'Uncategorized')
                    })
                   
                    print(f"\nRemoved {selected_item.get('name', 'item')} from inventory")
            else:
                print("\nInvalid selection")
        except ValueError:
            print("\nPlease enter a valid number")
        except Exception as e:
            log_error("item removal", e)

    def add_item_manually(self) -> None:
        """Add an item to inventory manually."""
        print("\nAdd Item Manually")
       
        try:
            # Get item details
            name = input("Item name: ")
            if not name:
                print("\nItem name cannot be empty")
                return
               
            # Get category
            print("\nCommon categories:")
            categories = ["Fruits", "Vegetables", "Dairy", "Meat", "Beverages", "Condiments", "Leftovers"]
            
            for i, cat in enumerate(categories, 1):
                print(f"{i}. {cat}")
               
            cat_choice = input("\nEnter category number or type a custom category: ")
            try:
                category = categories[int(cat_choice)-1]
            except (ValueError, IndexError):
                category = cat_choice
               
            quantity = input("Quantity (e.g., 2, half, 500g): ")
            notes = input("Notes (optional): ")
           
            # Create item
            item = {
                "name": self.vision_service.normalize_ingredient_name(name),
                "category": category,
                "quantity": quantity,
                "notes": notes,
                "added_date": datetime.now(),
                "last_seen": datetime.now()
            }
           
            # Save to database
            result = self.save_items([item])
           
            # Log the addition
            with DatabaseConnectionContext(self.database.get_client()) as db:
                db['session_logs'].insert_one({
                    "action": "item_added_manually",
                    "timestamp": datetime.now(),
                    "username": self.user_mgr.current_user['username'] if self.user_mgr.current_user else None,
                    "item_name": name,
                    "category": category
                })
           
            print(f"\nAdded {name} to inventory")
           
        except Exception as e:
            log_error("manual item addition", e)

    def edit_item(self) -> None:
        """Edit an existing inventory item."""
        items = self.get_current_inventory()
       
        if not items:
            print("\nNo items in inventory")
            return
       
        # Display items
        print("\nEdit Inventory Item")
        print("Select an item to edit:")
        
        for i, item in enumerate(items, 1):
            print(f"{i}. {item.get('name', 'Unknown')} ({item.get('category', 'Uncategorized')})")
        print("0. Cancel")
       
        try:
            choice = int(input("\nEnter item number: "))
            if choice == 0:
                return
               
            if 1 <= choice <= len(items):
                selected_item = items[choice-1]
               
                print(f"\nEditing: {selected_item.get('name')}")
                print("(Press Enter to keep current value)")
               
                name = input(f"Name [{selected_item.get('name', '')}]: ")
                category = input(f"Category [{selected_item.get('category', '')}]: ")
                quantity = input(f"Quantity [{selected_item.get('quantity', '')}]: ")
                notes = input(f"Notes [{selected_item.get('notes', '')}]: ")
               
                updates = {}
                if name: updates["name"] = self.vision_service.normalize_ingredient_name(name)
                if category: updates["category"] = category
                if quantity: updates["quantity"] = quantity
                if notes: updates["notes"] = notes
               
                if updates:
                    with DatabaseConnectionContext(self.database.get_client()) as db:
                        username = self.user_mgr.current_user['username']
                        # Update the specific item in the user's inventory array
                        for field, value in updates.items():
                            db['users'].update_one(
                                {
                                    "username": username,
                                    "inventory.name": selected_item['name'],
                                    "inventory.category": selected_item['category']
                                },
                                {"$set": {f"inventory.$.{field}": value}}
                            )
                       
                        # Log the edit
                        db['session_logs'].insert_one({
                            "action": "item_edited",
                            "timestamp": datetime.now(),
                            "username": username,
                            "item_name": selected_item["name"],
                            "changes": updates
                        })
                       
                    print(f"\nUpdated {selected_item.get('name', 'item')}")
                else:
                    print("\nNo changes made")
            else:
                print("\nInvalid selection")
        except ValueError:
            print("\nPlease enter a valid number")
        except Exception as e:
            log_error("item edit", e)

    # ----------------- Grocery List Management Methods -----------------

    def view_grocery_lists(self) -> None:
        """View and manage all saved grocery lists."""
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                if not self.user_mgr.current_user:
                    print("\nPlease log in to view grocery lists")
                    return
                
                username = self.user_mgr.current_user['username']
                
                while True:
                    # Get all saved grocery lists for the user
                    saved_lists = list(db['grocery_lists'].find(
                        {"username": username}
                    ).sort("created_at", -1))
                    
                    if not saved_lists:
                        print("\n📭 No saved grocery lists found.")
                        print("Create your first grocery list using 'Generate/Manage Grocery List' option!")
                        return
                    
                    self._display_saved_grocery_lists(saved_lists)
                    
                    try:
                        choice = input("\nEnter your choice: ").strip()
                        
                        if choice == '0':
                            break
                        elif choice == '1':
                            self._view_grocery_list_details(saved_lists, db)
                        elif choice == '2':
                            self._edit_existing_grocery_list(saved_lists, db, username)
                        elif choice == '3':
                            self._delete_grocery_list(saved_lists, db)
                        elif choice == '4':
                            self._export_grocery_list(saved_lists)
                        elif choice == '5':
                            self._compare_grocery_lists(saved_lists)
                        else:
                            print("\nInvalid choice. Please try again.")
                            
                    except KeyboardInterrupt:
                        print("\n\nExiting grocery list viewer...")
                        break
                    except Exception as e:
                        print(f"\nError: {str(e)}")
                        continue
        
        except Exception as e:
            log_error("viewing grocery lists", e)

    def _display_saved_grocery_lists(self, saved_lists):
        """Display all saved grocery lists with summary."""
        print("\n" + "="*60)
        print("📚 YOUR SAVED GROCERY LISTS")
        print("="*60)
        
        if not saved_lists:
            print("\n📭 No grocery lists found.")
            return
        
        print(f"\n📊 Total Lists: {len(saved_lists)}")
        print("\n" + "-"*60)
        
        for i, grocery_list in enumerate(saved_lists, 1):
            created = grocery_list['created_at'].strftime('%Y-%m-%d %H:%M')
            item_count = grocery_list.get('total_items', len(grocery_list.get('items', [])))
            list_type = grocery_list.get('type', 'basic')
            
            # Status indicator
            status_icon = "📋" if list_type == 'enhanced_grocery_list' else "📝"
            
            print(f"{i}. {status_icon} {grocery_list['name']}")
            print(f"   📅 Created: {created}")
            print(f"   📦 Items: {item_count}")
            print(f"   🏷️  Type: {list_type.replace('_', ' ').title()}")
            print("-" * 50)
        
        print("\n🔧 ACTIONS:")
        print("1. View List Details")
        print("2. Edit/Continue List")
        print("3. Delete List")
        print("4. Export List")
        print("5. Compare Lists")
        print("0. Back to Main Menu")

    def _view_grocery_list_details(self, saved_lists, db):
        """View detailed information about a specific grocery list."""
        if not saved_lists:
            return
        
        try:
            list_num = int(input(f"\nEnter list number (1-{len(saved_lists)}): "))
            if 1 <= list_num <= len(saved_lists):
                selected_list = saved_lists[list_num - 1]
                
                print("\n" + "="*60)
                print(f"📋 {selected_list['name'].upper()}")
                print("="*60)
                
                # List metadata
                created = selected_list['created_at'].strftime('%Y-%m-%d %H:%M')
                item_count = len(selected_list.get('items', []))
                
                print(f"📅 Created: {created}")
                print(f"📦 Total Items: {item_count}")
                print(f"🏷️  Type: {selected_list.get('type', 'basic').replace('_', ' ').title()}")
                
                # Group items by category
                items = selected_list.get('items', [])
                if items:
                    categories = {}
                    for item in items:
                        cat = item.get('category', 'Other')
                        if cat not in categories:
                            categories[cat] = []
                        categories[cat].append(item)
                    
                    print(f"\n📦 ITEMS BY CATEGORY:")
                    print("-" * 40)
                    
                    for category, cat_items in categories.items():
                        print(f"\n🏷️  {category.upper()} ({len(cat_items)} items)")
                        for item in cat_items:
                            # Item type indicator
                            if item.get('type') == 'smart_recommendation':
                                icon = "🧠"
                                extra = f" - {item.get('reason', '')}"
                            elif item.get('type') == 'custom':
                                icon = "✏️"
                                extra = f" - {item.get('notes', '')}" if item.get('notes') else ""
                            else:
                                icon = "🏪"
                                extra = ""
                            
                            quantity_str = f" ({item['quantity']})" if item.get('quantity') else ""
                            print(f"   {icon} {item['name']}{quantity_str}{extra}")
                
                # Shopping status if available
                if selected_list.get('shopping_status'):
                    completed = sum(1 for status in selected_list['shopping_status'].values() if status)
                    total = len(selected_list['shopping_status'])
                    print(f"\n✅ Shopping Progress: {completed}/{total} items completed")
                
                input("\nPress Enter to continue...")
            else:
                print("Invalid list number.")
        except ValueError:
            print("Please enter a valid number.")

    def _edit_existing_grocery_list(self, saved_lists, db, username):
        """Load an existing grocery list for editing."""
        if not saved_lists:
            return
        
        try:
            list_num = int(input(f"\nEnter list number to edit (1-{len(saved_lists)}): "))
            if 1 <= list_num <= len(saved_lists):
                selected_list = saved_lists[list_num - 1]
                
                print(f"\n🔄 Loading '{selected_list['name']}' for editing...")
                
                # Create grocery list structure from saved data
                self.current_grocery_list = {
                    "smart_recommendations": [],
                    "selected_items": [],
                    "custom_items": [],
                    "_existing_list_id": selected_list['_id']  # Track for updates
                }
                
                # Populate grocery list from saved data
                for item in selected_list.get('items', []):
                    if item.get('type') == 'custom':
                        self.current_grocery_list["custom_items"].append(item)
                    else:
                        self.current_grocery_list["selected_items"].append(item)
                
                # Get fresh smart recommendations
                current_inventory = self.get_current_inventory()
                self.current_grocery_list["smart_recommendations"] = self._get_smart_recommendations(current_inventory, db, username)
                
                # Continue with existing grocery list management
                self._continue_grocery_list_editing(db, username, selected_list['name'])
                
            else:
                print("Invalid list number.")
        except ValueError:
            print("Please enter a valid number.")

    def _continue_grocery_list_editing(self, db, username, list_name):
        """Continue editing an existing grocery list."""
        # Pre-defined common grocery items
        common_items = {
            "Dairy & Eggs": [
                "Milk", "Eggs", "Butter", "Cheese", "Yogurt", "Cream", "Cottage Cheese"
            ],
            "Grains & Cereals": [
                "Rice", "Wheat Flour", "Bread", "Pasta", "Oats", "Quinoa", "Barley"
            ],
            "Vegetables": [
                "Onions", "Potatoes", "Tomatoes", "Carrots", "Garlic", "Ginger", 
                "Bell Peppers", "Spinach", "Broccoli", "Cauliflower"
            ],
            "Fruits": [
                "Bananas", "Apples", "Oranges", "Lemons", "Grapes", "Berries"
            ],
            "Pantry Staples": [
                "Sugar", "Salt", "Oil", "Vinegar", "Spices", "Tea", "Coffee",
                "Baking Powder", "Vanilla Extract"
            ],
            "Proteins": [
                "Chicken", "Fish", "Beef", "Beans", "Lentils", "Tofu", "Nuts"
            ],
            "Beverages": [
                "Water", "Juice", "Soft Drinks", "Energy Drinks"
            ],
            "Condiments & Sauces": [
                "Ketchup", "Mustard", "Mayonnaise", "Soy Sauce", "Hot Sauce"
            ],
            "Frozen Foods": [
                "Frozen Vegetables", "Frozen Fruits", "Ice Cream", "Frozen Meals"
            ],
            "Cleaning & Household": [
                "Dish Soap", "Laundry Detergent", "Toilet Paper", "Paper Towels"
            ]
        }
        
        print(f"\n🔄 Editing: {list_name}")
        
        while True:
            self._display_grocery_menu(common_items)
            
            try:
                choice = input("\nEnter your choice: ").strip()
                
                if choice == '1':
                    self._browse_and_add_common_items(common_items)
                elif choice == '2':
                    self._add_custom_item()
                elif choice == '3':
                    self._remove_items_from_list()
                elif choice == '4':
                    self._view_full_grocery_list()
                elif choice == '5':
                    self._add_smart_recommendations()
                elif choice == '6':
                    if self._update_existing_grocery_list(db, username, list_name):
                        break
                elif choice == '7':
                    self._load_saved_grocery_list(db, username)
                elif choice == '0':
                    print("\nExiting grocery list editor...")
                    break
                else:
                    print("\nInvalid choice. Please try again.")
                    
            except KeyboardInterrupt:
                print("\n\nExiting grocery list editor...")
                break
            except Exception as e:
                print(f"\nError: {str(e)}")
                continue

    def _update_existing_grocery_list(self, db, username, original_name):
        """Update an existing grocery list in the database."""
        all_items = self.current_grocery_list["selected_items"] + self.current_grocery_list["custom_items"]
        
        if not all_items:
            print("\n📭 Cannot save an empty grocery list!")
            return False
        
        print(f"\n💾 Update grocery list with {len(all_items)} items?")
        update_choice = input("Update existing list? (y/n): ").strip().lower()
        
        if update_choice != 'y':
            return False
        
        # Option to rename
        new_name = input(f"New name (press Enter to keep '{original_name}'): ").strip()
        if not new_name:
            new_name = original_name
        
        try:
            list_id = self.current_grocery_list.get('_existing_list_id')
            if list_id:
                # Update existing list
                update_doc = {
                    "$set": {
                        "name": new_name,
                        "items": all_items,
                        "updated_at": datetime.now(),
                        "total_items": len(all_items)
                    }
                }
                
                result = db['grocery_lists'].update_one(
                    {"_id": list_id, "username": username},
                    update_doc
                )
                
                if result.modified_count > 0:
                    print(f"✅ Updated '{new_name}' successfully!")
                    return True
                else:
                    print("❌ Failed to update grocery list.")
                    return False
            else:
                # Fallback: create new list
                return self._save_grocery_list(db, username)
                
        except Exception as e:
            print(f"❌ Error updating grocery list: {str(e)}")
            return False

    def _delete_grocery_list(self, saved_lists, db):
        """Delete a saved grocery list."""
        if not saved_lists:
            return
        
        try:
            list_num = int(input(f"\nEnter list number to delete (1-{len(saved_lists)}): "))
            if 1 <= list_num <= len(saved_lists):
                selected_list = saved_lists[list_num - 1]
                
                print(f"\n⚠️  DELETE CONFIRMATION")
                print(f"List: {selected_list['name']}")
                print(f"Items: {len(selected_list.get('items', []))}")
                print(f"Created: {selected_list['created_at'].strftime('%Y-%m-%d %H:%M')}")
                
                confirm = input("\nAre you sure you want to delete this list? (type 'DELETE' to confirm): ")
                
                if confirm == 'DELETE':
                    result = db['grocery_lists'].delete_one({"_id": selected_list['_id']})
                    if result.deleted_count > 0:
                        print(f"✅ Deleted '{selected_list['name']}' successfully!")
                    else:
                        print("❌ Failed to delete grocery list.")
                else:
                    print("❌ Deletion cancelled.")
            else:
                print("Invalid list number.")
        except ValueError:
            print("Please enter a valid number.")

    def _export_grocery_list(self, saved_lists):
        """Export a grocery list to text format."""
        if not saved_lists:
            return
        
        try:
            list_num = int(input(f"\nEnter list number to export (1-{len(saved_lists)}): "))
            if 1 <= list_num <= len(saved_lists):
                selected_list = saved_lists[list_num - 1]
                
                # Create export text
                export_text = f"🛒 {selected_list['name'].upper()}\n"
                export_text += f"Generated: {selected_list['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
                export_text += "=" * 50 + "\n\n"
                
                # Group by category
                items = selected_list.get('items', [])
                categories = {}
                for item in items:
                    cat = item.get('category', 'Other')
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(item)
                
                for category, cat_items in categories.items():
                    export_text += f"{category.upper()}:\n"
                    for item in cat_items:
                        quantity_str = f" ({item['quantity']})" if item.get('quantity') else ""
                        export_text += f"  ☐ {item['name']}{quantity_str}\n"
                    export_text += "\n"
                
                export_text += f"Total Items: {len(items)}\n"
                
                # Save to file
                filename = f"grocery_list_{selected_list['name'].replace(' ', '_').lower()}.txt"
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(export_text)
                    print(f"✅ Exported to '{filename}'")
                except Exception as e:
                    print(f"❌ Error saving file: {str(e)}")
                    print("\n📄 LIST CONTENT:")
                    print(export_text)
            else:
                print("Invalid list number.")
        except ValueError:
            print("Please enter a valid number.")

    def _compare_grocery_lists(self, saved_lists):
        """Compare two grocery lists to see differences."""
        if len(saved_lists) < 2:
            print("\nNeed at least 2 saved lists to compare.")
            return
        
        try:
            print(f"\nSelect two lists to compare:")
            list1_num = int(input(f"First list (1-{len(saved_lists)}): "))
            list2_num = int(input(f"Second list (1-{len(saved_lists)}): "))
            
            if (1 <= list1_num <= len(saved_lists) and
                1 <= list2_num <= len(saved_lists) and
                list1_num != list2_num):
                
                list1 = saved_lists[list1_num - 1]
                list2 = saved_lists[list2_num - 1]
                
                # Get item names from both lists
                items1 = {item['name'].lower() for item in list1.get('items', [])}
                items2 = {item['name'].lower() for item in list2.get('items', [])}
                
                # Find differences
                only_in_list1 = items1 - items2
                only_in_list2 = items2 - items1
                common_items = items1 & items2
                
                print(f"\n📊 COMPARISON: '{list1['name']}' vs '{list2['name']}'")
                print("=" * 60)
                
                print(f"\n🔗 Common Items ({len(common_items)}):")
                for item in sorted(common_items):
                    print(f"  ✅ {item.title()}")
                
                print(f"\n📋 Only in '{list1['name']}' ({len(only_in_list1)}):")
                for item in sorted(only_in_list1):
                    print(f"  🔸 {item.title()}")
                
                print(f"\n📋 Only in '{list2['name']}' ({len(only_in_list2)}):")
                for item in sorted(only_in_list2):
                    print(f"  🔹 {item.title()}")
                
                print(f"\n📈 SUMMARY:")
                print(f"  List 1 Total: {len(items1)} items")
                print(f"  List 2 Total: {len(items2)} items")
                print(f"  Common: {len(common_items)} items")
                print(f"  Unique to List 1: {len(only_in_list1)} items")
                print(f"  Unique to List 2: {len(only_in_list2)} items")
                
                input("\nPress Enter to continue...")
            else:
                print("Invalid list numbers or same list selected twice.")
        except ValueError:
            print("Please enter valid numbers.")

    def generate_grocery_list(self) -> None:
        """Generate a smart grocery list with option to continue existing list."""
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                if not self.user_mgr.current_user:
                    print("\nPlease log in to generate grocery lists")
                    return
                
                username = self.user_mgr.current_user['username']
                
                # Check for recent grocery lists
                recent_lists = list(db['grocery_lists'].find(
                    {"username": username}
                ).sort("created_at", -1).limit(3))
                
                if recent_lists:
                    print(f"\n📚 Found {len(recent_lists)} recent grocery list(s):")
                    for i, glist in enumerate(recent_lists, 1):
                        created = glist['created_at'].strftime('%Y-%m-%d %H:%M')
                        item_count = len(glist.get('items', []))
                        print(f"{i}. {glist['name']} ({item_count} items) - {created}")
                    
                    print("\n🔧 OPTIONS:")
                    print("1. Create New Grocery List")
                    print("2. Continue Existing List")
                    print("0. Back to Main Menu")
                    
                    choice = input("\nWhat would you like to do? ").strip()
                    
                    if choice == '2':
                        try:
                            list_num = int(input(f"Which list to continue (1-{len(recent_lists)})? "))
                            if 1 <= list_num <= len(recent_lists):
                                selected_list = recent_lists[list_num - 1]
                                self._edit_existing_grocery_list([selected_list], db, username)
                                return
                            else:
                                print("Invalid selection, creating new list...")
                        except ValueError:
                            print("Invalid input, creating new list...")
                    elif choice == '0':
                        return
                    # If choice == '1' or invalid, continue to create new list
                
                # Create new grocery list (existing logic)
                current_inventory = self.get_current_inventory()
                
                # Pre-defined common grocery items organized by category
                common_items = {
                    "Dairy & Eggs": [
                        "Milk", "Eggs", "Butter", "Cheese", "Yogurt", "Cream", "Cottage Cheese"
                    ],
                    "Grains & Cereals": [
                        "Rice", "Wheat Flour", "Bread", "Pasta", "Oats", "Quinoa", "Barley"
                    ],
                    "Vegetables": [
                        "Onions", "Potatoes", "Tomatoes", "Carrots", "Garlic", "Ginger", 
                        "Bell Peppers", "Spinach", "Broccoli", "Cauliflower"
                    ],
                    "Fruits": [
                        "Bananas", "Apples", "Oranges", "Lemons", "Grapes", "Berries"
                    ],
                    "Pantry Staples": [
                        "Sugar", "Salt", "Oil", "Vinegar", "Spices", "Tea", "Coffee",
                        "Baking Powder", "Vanilla Extract"
                    ],
                    "Proteins": [
                        "Chicken", "Fish", "Beef", "Beans", "Lentils", "Tofu", "Nuts"
                    ],
                    "Beverages": [
                        "Water", "Juice", "Soft Drinks", "Energy Drinks"
                    ],
                    "Condiments & Sauces": [
                        "Ketchup", "Mustard", "Mayonnaise", "Soy Sauce", "Hot Sauce"
                    ],
                    "Frozen Foods": [
                        "Frozen Vegetables", "Frozen Fruits", "Ice Cream", "Frozen Meals"
                    ],
                    "Cleaning & Household": [
                        "Dish Soap", "Laundry Detergent", "Toilet Paper", "Paper Towels"
                    ]
                }
                
                # Get smart recommendations based on consumption patterns
                smart_recommendations = self._get_smart_recommendations(current_inventory, db, username)
                
                # Initialize grocery list
                self.current_grocery_list = {
                    "smart_recommendations": smart_recommendations,
                    "selected_items": [],
                    "custom_items": []
                }
                
                print("\n🆕 Creating new grocery list...")
                
                while True:
                    self._display_grocery_menu(common_items)
                    
                    try:
                        choice = input("\nEnter your choice: ").strip()
                        
                        if choice == '1':
                            self._browse_and_add_common_items(common_items)
                        elif choice == '2':
                            self._add_custom_item()
                        elif choice == '3':
                            self._remove_items_from_list()
                        elif choice == '4':
                            self._view_full_grocery_list()
                        elif choice == '5':
                            self._add_smart_recommendations()
                        elif choice == '6':
                            if self._save_grocery_list(db, username):
                                break
                        elif choice == '7':
                            self._load_saved_grocery_list(db, username)
                        elif choice == '0':
                            print("\nExiting grocery list manager...")
                            break
                        else:
                            print("\nInvalid choice. Please try again.")
                            
                    except KeyboardInterrupt:
                        print("\n\nExiting grocery list manager...")
                        break
                    except Exception as e:
                        print(f"\nError: {str(e)}")
                        continue
        
        except Exception as e:
            log_error("grocery list generation", e)

    def _get_smart_recommendations(self, current_inventory, db, username):
        """Get smart recommendations based on consumption patterns."""
        recommendations = []
        threshold_date = datetime.now() - timedelta(days=7)
        
        # Get items that are running low or consumed
        inventory_items = {(item['name'].lower(), item['category'].lower()): item 
                        for item in current_inventory}
        
        # Check recently consumed items
        consumed_items = db['users'].aggregate([
            {"$match": {"username": username}},
            {"$unwind": "$consumption_history"},
            {"$match": {
                "consumption_history.timestamp": {"$gte": threshold_date},
                "consumption_history.action": "consumed"
            }},
            {"$group": {
                "_id": {
                    "name": "$consumption_history.item_name",
                    "category": "$consumption_history.category"
                },
                "count": {"$sum": 1},
                "last_consumed": {"$max": "$consumption_history.timestamp"}
            }}
        ])
        
        # Process recommendations
        for item in consumed_items:
            item_name = item['_id']['name']
            item_key = (item_name.lower(), item['_id']['category'].lower())
            
            # Check if item is already in inventory
            if item_key in inventory_items:
                inv_item = inventory_items[item_key]
                try:
                    current_qty = self._extract_quantity(inv_item.get('quantity', '1'))
                    if current_qty > 0.5:
                        continue
                except:
                    pass
            
            # Check consumption pattern
            pattern = self.consumption_patterns.get(item_name.lower(), {})
            consumption_rate = pattern.get('consumption_rate', 0)
            days_since_last = (datetime.now() - item['last_consumed']).days if item['last_consumed'] else 0
            
            # Generate recommendation based on usage pattern
            if consumption_rate > 0.3:
                urgency = "High"
                reason = f"Frequently used ({consumption_rate:.1f}/day)"
            elif days_since_last < 3:
                urgency = "Medium"
                reason = "Recently consumed"
            else:
                urgency = "Low"
                reason = "Occasionally used"
            
            recommendations.append({
                "name": item_name,
                "category": item['_id']['category'],
                "reason": reason,
                "urgency": urgency,
                "last_consumed": item['last_consumed'],
                "consumption_rate": consumption_rate
            })
        
        return sorted(recommendations, key=lambda x: (
            0 if x['urgency'] == 'High' else 1 if x['urgency'] == 'Medium' else 2,
            -x['consumption_rate']
        ))

    def _display_grocery_menu(self, common_items):
        """Display the main grocery list management menu."""
        print("\n" + "="*60)
        print("🛒 SMART GROCERY LIST MANAGER")
        print("="*60)
        
        # Show current list summary
        total_items = len(self.current_grocery_list["selected_items"]) + len(self.current_grocery_list["custom_items"])
        smart_count = len(self.current_grocery_list["smart_recommendations"])
        
        print(f"\n📋 Current List: {total_items} items")
        if smart_count > 0:
            print(f"🧠 Smart Recommendations Available: {smart_count} items")
        
        print("\n🏪 MENU OPTIONS:")
        print("1. Browse & Add Common Items")
        print("2. Add Custom Item")
        print("3. Remove Items from List")
        print("4. View Full Grocery List")
        print("5. Add Smart Recommendations")
        print("6. Save & Finish")
        print("7. Load Saved List")
        print("0. Exit")

    def _browse_and_add_common_items(self, common_items):
        """Browse and add items from pre-defined common items."""
        while True:
            print("\n" + "="*50)
            print("🏪 COMMON GROCERY ITEMS")
            print("="*50)
            
            categories = list(common_items.keys())
            for i, category in enumerate(categories, 1):
                item_count = len(common_items[category])
                print(f"{i}. {category} ({item_count} items)")
            print("0. Back to main menu")
            
            try:
                choice = int(input("\nSelect category: "))
                if choice == 0:
                    break
                elif 1 <= choice <= len(categories):
                    selected_category = categories[choice - 1]
                    self._add_items_from_category(common_items[selected_category], selected_category)
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a valid number.")

    def _add_items_from_category(self, items, category):
        """Add items from a specific category."""
        while True:
            print(f"\n📦 {category.upper()}")
            print("-" * len(category))
            
            # Show items with selection status
            for i, item in enumerate(items, 1):
                status = "✅" if self._is_item_in_list(item, category) else "⬜"
                print(f"{status} {i}. {item}")
            
            print("\n🔧 OPTIONS:")
            print("A. Add All Items")
            print("R. Remove All Items")
            print("0. Back to categories")
            
            choice = input("\nEnter item number(s) separated by commas, or option: ").strip()
            
            if choice == '0':
                break
            elif choice.upper() == 'A':
                self._add_all_items_from_category(items, category)
                print(f"✅ Added all items from {category}")
            elif choice.upper() == 'R':
                self._remove_all_items_from_category(items, category)
                print(f"❌ Removed all items from {category}")
            else:
                self._toggle_items_by_numbers(items, category, choice)

    def _toggle_items_by_numbers(self, items, category, choice):
        """Toggle items based on number selection."""
        try:
            numbers = [int(x.strip()) for x in choice.split(',')]
            for num in numbers:
                if 1 <= num <= len(items):
                    item_name = items[num - 1]
                    if self._is_item_in_list(item_name, category):
                        self._remove_item_from_list(item_name, category)
                        print(f"❌ Removed: {item_name}")
                    else:
                        self.current_grocery_list["selected_items"].append({
                            "name": item_name,
                            "category": category,
                            "type": "common"
                        })
                        print(f"✅ Added: {item_name}")
                else:
                    print(f"Invalid item number: {num}")
        except ValueError:
            print("Invalid input. Please enter numbers separated by commas.")

    def _add_custom_item(self):
        """Add a custom item to the grocery list."""
        print("\n➕ ADD CUSTOM ITEM")
        print("-" * 20)
        
        name = input("Item name: ").strip()
        if not name:
            print("Item name cannot be empty.")
            return
        
        # Suggest categories
        print("\nSuggested categories:")
        categories = ["Dairy & Eggs", "Grains & Cereals", "Vegetables", "Fruits", 
                    "Pantry Staples", "Proteins", "Beverages", "Other"]
        
        for i, cat in enumerate(categories, 1):
            print(f"{i}. {cat}")
        
        cat_input = input("\nEnter category number or custom category: ").strip()
        try:
            category = categories[int(cat_input) - 1]
        except (ValueError, IndexError):
            category = cat_input if cat_input else "Other"
        
        quantity = input("Quantity (optional): ").strip()
        notes = input("Notes (optional): ").strip()
        
        custom_item = {
            "name": name,
            "category": category,
            "quantity": quantity,
            "notes": notes,
            "type": "custom"
        }
        
        self.current_grocery_list["custom_items"].append(custom_item)
        print(f"✅ Added custom item: {name}")

    def _remove_items_from_list(self):
        """Remove items from the current grocery list."""
        all_items = self.current_grocery_list["selected_items"] + self.current_grocery_list["custom_items"]
        
        if not all_items:
            print("\n📭 Your grocery list is empty!")
            return
        
        print("\n❌ REMOVE ITEMS")
        print("-" * 15)
        
        for i, item in enumerate(all_items, 1):
            item_type = "🏪" if item.get("type") == "common" else "✏️"
            quantity_str = f" ({item['quantity']})" if item.get('quantity') else ""
            print(f"{i}. {item_type} {item['name']}{quantity_str} - {item['category']}")
        
        print("\n0. Back to main menu")
        
        try:
            choice = input("\nEnter item number(s) to remove (comma-separated): ").strip()
            if choice == '0':
                return
            
            numbers = [int(x.strip()) for x in choice.split(',')]
            numbers.sort(reverse=True)  # Remove from end to avoid index issues
            
            removed_items = []
            for num in numbers:
                if 1 <= num <= len(all_items):
                    item_index = num - 1
                    if item_index < len(self.current_grocery_list["selected_items"]):
                        removed_item = self.current_grocery_list["selected_items"].pop(item_index)
                    else:
                        custom_index = item_index - len(self.current_grocery_list["selected_items"])
                        removed_item = self.current_grocery_list["custom_items"].pop(custom_index)
                    removed_items.append(removed_item['name'])
            
            if removed_items:
                print(f"❌ Removed: {', '.join(removed_items)}")
            
        except ValueError:
            print("Invalid input. Please enter valid numbers.")

    def _view_full_grocery_list(self):
        """Display the complete grocery list."""
        all_items = self.current_grocery_list["selected_items"] + self.current_grocery_list["custom_items"]
        
        if not all_items:
            print("\n📭 Your grocery list is empty!")
            return
        
        print("\n" + "="*50)
        print("🛒 YOUR GROCERY LIST")
        print("="*50)
        
        # Group by category
        categories = {}
        for item in all_items:
            cat = item['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(item)
        
        for category, items in categories.items():
            print(f"\n📦 {category.upper()}")
            print("-" * len(category))
            
            for item in items:
                item_type = "🏪" if item.get("type") == "common" else "✏️"
                quantity_str = f" ({item['quantity']})" if item.get('quantity') else ""
                notes_str = f" - {item['notes']}" if item.get('notes') else ""
                print(f"  {item_type} {item['name']}{quantity_str}{notes_str}")
        
        print(f"\n📊 Total Items: {len(all_items)}")
        input("\nPress Enter to continue...")

    def _add_smart_recommendations(self):
        """Add items from smart recommendations."""
        if not self.current_grocery_list["smart_recommendations"]:
            print("\n🤖 No smart recommendations available at this time.")
            return
        
        print("\n🧠 SMART RECOMMENDATIONS")
        print("="*30)
        print("Based on your consumption patterns:")
        
        for i, item in enumerate(self.current_grocery_list["smart_recommendations"], 1):
            urgency_icon = "🔴" if item['urgency'] == 'High' else "🟡" if item['urgency'] == 'Medium' else "⚪"
            print(f"{i}. {urgency_icon} {item['name']} - {item['reason']}")
        
        print("\n0. Back to main menu")
        
        try:
            choice = input("\nEnter recommendation number(s) to add (comma-separated): ").strip()
            if choice == '0':
                return
            
            numbers = [int(x.strip()) for x in choice.split(',')]
            added_items = []
            
            for num in numbers:
                if 1 <= num <= len(self.current_grocery_list["smart_recommendations"]):
                    rec = self.current_grocery_list["smart_recommendations"][num - 1]
                    self.current_grocery_list["selected_items"].append({
                        "name": rec['name'],
                        "category": rec['category'],
                        "type": "smart_recommendation",
                        "urgency": rec['urgency'],
                        "reason": rec['reason']
                    })
                    added_items.append(rec['name'])
            
            if added_items:
                print(f"✅ Added smart recommendations: {', '.join(added_items)}")
        
        except ValueError:
            print("Invalid input. Please enter valid numbers.")

    def _save_grocery_list(self, db, username):
        """Save the grocery list to database."""
        all_items = self.current_grocery_list["selected_items"] + self.current_grocery_list["custom_items"]
        
        if not all_items:
            print("\n📭 Cannot save an empty grocery list!")
            return False
        
        print(f"\n💾 Save grocery list with {len(all_items)} items?")
        list_name = input("Enter a name for this list (or press Enter for auto-name): ").strip()
        
        if not list_name:
            list_name = f"Grocery List {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        grocery_list_doc = {
            "username": username,
            "name": list_name,
            "items": all_items,
            "created_at": datetime.now(),
            "type": "enhanced_grocery_list",
            "total_items": len(all_items)
        }
        
        try:
            db['grocery_lists'].insert_one(grocery_list_doc)
            print(f"✅ Saved '{list_name}' successfully!")
            return True
        except Exception as e:
            print(f"❌ Error saving grocery list: {str(e)}")
            return False

    def _load_saved_grocery_list(self, db, username):
        """Load a previously saved grocery list."""
        try:
            saved_lists = list(db['grocery_lists'].find(
                {"username": username}
            ).sort("created_at", -1).limit(10))
            
            if not saved_lists:
                print("\n📭 No saved grocery lists found.")
                return
            
            print("\n📚 SAVED GROCERY LISTS")
            print("="*25)
            
            for i, saved_list in enumerate(saved_lists, 1):
                created = saved_list['created_at'].strftime('%Y-%m-%d %H:%M')
                item_count = len(saved_list.get('items', []))
                print(f"{i}. {saved_list['name']} ({item_count} items) - {created}")
            
            print("0. Back to main menu")
            
            choice = int(input("\nSelect list to load: "))
            if choice == 0:
                return
            
            if 1 <= choice <= len(saved_lists):
                selected_list = saved_lists[choice - 1]
                
                # Clear current list and load selected one
                self.current_grocery_list["selected_items"] = []
                self.current_grocery_list["custom_items"] = []
                
                for item in selected_list['items']:
                    if item.get('type') == 'custom':
                        self.current_grocery_list["custom_items"].append(item)
                    else:
                        self.current_grocery_list["selected_items"].append(item)
                
                print(f"✅ Loaded '{selected_list['name']}' with {len(selected_list['items'])} items")
            else:
                print("Invalid selection.")
        
        except ValueError:
            print("Please enter a valid number.")
        except Exception as e:
            print(f"Error loading grocery lists: {str(e)}")

    def _is_item_in_list(self, item_name, category):
        """Check if an item is already in the grocery list."""
        all_items = self.current_grocery_list["selected_items"] + self.current_grocery_list["custom_items"]
        return any(item['name'].lower() == item_name.lower() and 
                item['category'].lower() == category.lower() 
                for item in all_items)

    def _remove_item_from_list(self, item_name, category):
        """Remove a specific item from the grocery list."""
        self.current_grocery_list["selected_items"] = [
            item for item in self.current_grocery_list["selected_items"]
            if not (item['name'].lower() == item_name.lower() and 
                item['category'].lower() == category.lower())
        ]

    def _add_all_items_from_category(self, items, category):
        """Add all items from a category."""
        for item in items:
            if not self._is_item_in_list(item, category):
                self.current_grocery_list["selected_items"].append({
                    "name": item,
                    "category": category,
                    "type": "common"
                })

    def _remove_all_items_from_category(self, items, category):
        """Remove all items from a category."""
        for item in items:
            self._remove_item_from_list(item, category)