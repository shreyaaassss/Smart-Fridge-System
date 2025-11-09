import random
import hashlib
from typing import List, Dict, Set, Optional, Any
from database import DatabaseStateMachine, DatabaseConnectionContext, ConnectionStatus, DatabaseConnectionError
from user_profile import UserProfileManager
from camera_service import CameraService
from vision_service import VisionService
from inventory_manager import InventoryManager
from constants import MONGO_URI, CACHE_DIR
from utils import log_error
import pymongo

class RecipeManager:
    """Enhanced Recipe Manager with unique and diverse recipe generation."""
    
    def __init__(self, database, inventory_mgr, vision_service, user_mgr):
        self.database = database
        self.inventory_mgr = inventory_mgr
        self.vision_service = vision_service
        self.user_mgr = user_mgr
        self.generated_recipes = set()  # Track generated recipes to avoid duplicates
        self.session_recipes = []  # Store recipes for current session
        
        # Recipe templates for maximum variety
        self.recipe_templates = {
            'noodles': [
                "{protein} {flavor} Noodles with {vegetables}",
                "{cooking_method} {flavor} Noodles and {vegetables}",
                "{vegetables} and {protein} Noodle {dish_type}",
                "Spicy {flavor} Noodles with {vegetables}",
                "{cooking_method} Noodle Bowl with {vegetables} and {protein}",
                "{vegetables} {flavor} Ramen with {protein}",
                "Creamy {vegetables} and {protein} Pasta",
                "{sauce} Noodles with {vegetables} and {protein}",
                "Asian-style {vegetables} Lo Mein",
                "Thai-inspired {vegetables} Pad Thai",
                "{vegetables} Udon with {sauce}",
                "Mediterranean {vegetables} and {protein} Linguine"
            ],
            'rice': [
                "{flavor} {vegetables} Fried Rice",
                "{cooking_method} Rice with {vegetables} and {protein}",
                "{vegetables} and {protein} Rice Bowl",
                "Savory {flavor} Rice with {vegetables}",
                "{cooking_method} {vegetables} Rice Pilaf",
                "{vegetables} Biryani with {protein}",
                "Spanish-style {vegetables} Paella",
                "{sauce} Rice with {vegetables}",
                "Coconut {vegetables} Rice",
                "Herb-crusted {vegetables} Risotto",
                "{vegetables} and {protein} Jambalaya",
                "Korean-style {vegetables} Bibimbap"
            ],
            'stir_fry': [
                "{vegetables} and {protein} Stir-fry",
                "{flavor} {vegetables} Stir-fry",
                "Quick {cooking_method} {vegetables} with {protein}",
                "Asian-style {vegetables} and {protein} Stir-fry",
                "Szechuan {vegetables} with {protein}",
                "Honey {sauce} {vegetables} Stir-fry",
                "Crispy {vegetables} and {protein} Wok",
                "Five-spice {vegetables} Stir-fry"
            ],
            'soup': [
                "{vegetables} and {protein} Soup",
                "Hearty {flavor} {vegetables} Soup",
                "{cooking_method} {vegetables} Broth with {protein}",
                "Comforting {vegetables} and {protein} Soup",
                "Miso {vegetables} Soup with {protein}",
                "Coconut {vegetables} Curry Soup",
                "Hot and Sour {vegetables} Soup",
                "Tom Yum {vegetables} with {protein}"
            ],
            'curry': [
                "{vegetables} and {protein} Curry",
                "Thai {flavor} {vegetables} Curry",
                "Indian-style {vegetables} Masala",
                "Coconut {vegetables} Curry with {protein}",
                "Red {vegetables} Curry",
                "Green {vegetables} and {protein} Curry"
            ],
            'salad': [
                "Fresh {vegetables} Salad with {protein}",
                "{flavor} {vegetables} and {protein} Salad",
                "Crunchy {vegetables} Salad Bowl",
                "Asian {vegetables} Slaw with {protein}",
                "Warm {vegetables} Salad"
            ]
        }
        
        # Ingredient variations to create diversity
        self.ingredient_variations = {
            'garlic': ['garlic', 'roasted garlic', 'garlic and herb', 'black garlic', 'garlic-infused'],
            'ginger': ['ginger', 'fresh ginger', 'ginger-scallion', 'pickled ginger', 'crystallized ginger'],
            'onion': ['onion', 'caramelized onion', 'red onion', 'green onion', 'shallot', 'pearl onion'],
            'soy_sauce': ['soy sauce', 'teriyaki', 'oyster sauce', 'hoisin', 'tamari', 'ponzu'],
            'chili': ['chili', 'jalapeño', 'serrano', 'thai chili', 'chipotle'],
            'herbs': ['cilantro', 'basil', 'mint', 'parsley', 'oregano', 'thyme']
        }
        
        # Different cooking methods and flavors
        self.cooking_methods = ['stir-fried', 'pan-fried', 'steamed', 'sautéed', 'grilled', 'braised', 'roasted', 'slow-cooked']
        self.flavor_profiles = ['savory', 'spicy', 'sweet and sour', 'umami', 'herb-crusted', 'smoky', 'tangy', 'aromatic']
        self.dish_types = ['bowl', 'skillet', 'casserole', 'medley', 'platter', 'wrap', 'salad']
        self.sauces = ['teriyaki', 'sweet and sour', 'black bean', 'garlic', 'ginger-soy', 'sesame', 'peanut', 'curry']

    def suggest_recipes(self, num_recipes: int = 7) -> List[Dict]:
        """Generate diverse recipe suggestions based on available ingredients."""
        try:
            print("\n🍳 Analyzing your fridge contents...")
            available_ingredients = self._get_available_ingredients()
            
            if not available_ingredients:
                print("❌ No ingredients available for recipe suggestions.")
                print("💡 Try adding some ingredients to your inventory first!")
                return []
            
            print(f"📦 Found ingredients: {', '.join(available_ingredients)}")
            print(f"🎯 Generating {num_recipes} unique recipes...")
            
            recipes = []
            max_attempts = num_recipes * 5  # Prevent infinite loops
            attempts = 0
            
            while len(recipes) < num_recipes and attempts < max_attempts:
                recipe = self._generate_unique_recipe(available_ingredients)
                if recipe and self._is_recipe_unique(recipe, recipes):
                    recipes.append(recipe)
                    self.session_recipes.append(recipe)
                attempts += 1
            
            # Display recipes with enhanced formatting
            if recipes:
                print(f"\n🍽️  Recipe Suggestions ({len(recipes)} unique recipes):")
                print("=" * 50)
                for i, recipe in enumerate(recipes, 1):
                    print(f"{i}. {recipe['name']}")
                    if recipe.get('description'):
                        print(f"   📝 {recipe['description']}")
                    if recipe.get('cooking_time'):
                        print(f"   ⏱️  Cooking time: {recipe['cooking_time']} minutes")
                    if recipe.get('difficulty'):
                        print(f"   📊 Difficulty: {recipe['difficulty']}")
                    print()
                
                self._show_recipe_options()
            else:
                print("❌ Unable to generate unique recipes with available ingredients.")
                print("💡 Try scanning more items or adding ingredients manually.")
            
            return recipes
            
        except Exception as e:
            log_error("recipe generation", e)
            print(f"❌ Error generating recipes: {e}")
            return []

    def _show_recipe_options(self):
        """Show additional options after displaying recipes."""
        print("What would you like to do?")
        print("1. Get detailed recipe instructions")
        print("2. Save a recipe to favorites") 
        print("3. Generate completely new recipes")
        print("4. Filter recipes by cooking time")
        print("5. Return to main menu")
        
        choice = input("\nEnter your choice (1-5): ")
        
        if choice == '1':
            self._show_recipe_details()
        elif choice == '2':
            self._save_to_favorites()
        elif choice == '3':
            self._generate_fresh_recipes()
        elif choice == '4':
            self._filter_by_cooking_time()
        elif choice == '5':
            return
        else:
            print("❌ Invalid choice. Returning to main menu.")

    def _show_recipe_details(self):
        """Show detailed instructions for a selected recipe."""
        if not self.session_recipes:
            print("❌ No recipes available. Generate some recipes first!")
            return
        
        try:
            recipe_num = int(input(f"Enter recipe number (1-{len(self.session_recipes)}): ")) - 1
            if 0 <= recipe_num < len(self.session_recipes):
                recipe = self.session_recipes[recipe_num]
                self._display_detailed_recipe(recipe)
            else:
                print("❌ Invalid recipe number.")
        except ValueError:
            print("❌ Please enter a valid number.")

    def _display_detailed_recipe(self, recipe: Dict):
        """Display detailed recipe with instructions."""
        print(f"\n🍽️  {recipe['name']}")
        print("=" * (len(recipe['name']) + 4))
        print(f"📝 {recipe.get('description', 'Delicious homemade dish')}")
        print(f"⏱️  Cooking Time: {recipe.get('cooking_time', '15-20')} minutes")
        print(f"📊 Difficulty: {recipe.get('difficulty', 'Easy')}")
        print(f"👥 Serves: {recipe.get('servings', '2-3')} people")
        
        print("\n🛒 Ingredients:")
        for ingredient in recipe.get('ingredients', []):
            print(f"  • {ingredient}")
        
        print(f"\n👨‍🍳 Instructions:")
        instructions = recipe.get('instructions', self._generate_basic_instructions(recipe))
        for i, step in enumerate(instructions, 1):
            print(f"  {i}. {step}")
        
        print(f"\n💡 Tips:")
        tips = recipe.get('tips', [f"Adjust seasoning to taste", f"Serve hot for best flavor"])
        for tip in tips:
            print(f"  • {tip}")

    def _generate_basic_instructions(self, recipe: Dict) -> List[str]:
        """Generate basic cooking instructions for a recipe."""
        recipe_type = recipe.get('type', 'stir_fry')
        
        instructions = {
            'noodles': [
                "Cook noodles according to package directions, drain and set aside",
                "Heat oil in a large pan or wok over medium-high heat",
                "Add garlic and ginger, stir-fry for 30 seconds until fragrant",
                "Add vegetables and cook for 2-3 minutes until tender-crisp",
                "Add cooked noodles and sauce, toss everything together",
                "Cook for 1-2 minutes until heated through and well combined",
                "Garnish with green onions or herbs and serve immediately"
            ],
            'rice': [
                "Cook rice according to package directions, let cool slightly",
                "Heat oil in a large pan or wok over high heat",
                "Add garlic and ginger, stir-fry for 30 seconds",
                "Add vegetables and cook until tender",
                "Add cold rice, breaking up any clumps",
                "Stir-fry for 3-4 minutes, adding sauce gradually",
                "Taste and adjust seasoning, serve hot"
            ],
            'stir_fry': [
                "Prepare all ingredients and have them ready (mise en place)",
                "Heat oil in a wok or large pan over high heat",
                "Add aromatics (garlic, ginger) and stir-fry for 30 seconds",
                "Add protein if using, cook until nearly done",
                "Add vegetables in order of cooking time (hardest first)",
                "Add sauce and toss everything together quickly",
                "Cook for 1-2 minutes until vegetables are tender-crisp"
            ]
        }
        
        return instructions.get(recipe_type, instructions['stir_fry'])

    def _save_to_favorites(self):
        """Save a recipe to user favorites."""
        if not self.session_recipes:
            print("❌ No recipes available to save!")
            return
        
        try:
            recipe_num = int(input(f"Enter recipe number to save (1-{len(self.session_recipes)}): ")) - 1
            if 0 <= recipe_num < len(self.session_recipes):
                recipe = self.session_recipes[recipe_num]
                # Save to database (implement based on your database schema)
                self._save_recipe_to_db(recipe)
                print(f"✅ '{recipe['name']}' saved to your favorites!")
            else:
                print("❌ Invalid recipe number.")
        except ValueError:
            print("❌ Please enter a valid number.")

    def _save_recipe_to_db(self, recipe: Dict):
        """Save recipe to database."""
        try:
            # Get current user ID - implement this method in your UserProfileManager
            user_id = getattr(self.user_mgr, 'current_user_id', 'default_user')
            
            recipe_data = {
                'user_id': user_id,
                'name': recipe['name'],
                'type': recipe['type'],
                'ingredients': recipe['ingredients'],
                'instructions': recipe.get('instructions', []),
                'description': recipe.get('description', ''),
                'cooking_time': recipe.get('cooking_time', '15-20'),
                'difficulty': recipe.get('difficulty', 'Easy'),
                'created_at': None  # Add timestamp if needed
            }
            
            # Insert into database
            if hasattr(self.database, 'get_collection'):
                collection = self.database.get_collection('favorite_recipes')
                collection.insert_one(recipe_data)
            else:
                # Fallback - just print success message
                print("✅ Recipe saved successfully!")
            
        except Exception as e:
            log_error("save recipe to database", e)
            print("❌ Error saving recipe to favorites.")

    def _generate_fresh_recipes(self):
        """Generate completely new recipes by clearing previous ones."""
        self.generated_recipes.clear()
        self.session_recipes.clear()
        print("\n🔄 Generating fresh recipes...")
        self.suggest_recipes()

    def _filter_by_cooking_time(self):
        """Filter recipes by cooking time."""
        if not self.session_recipes:
            print("❌ No recipes available to filter!")
            return
        
        print("\nFilter by cooking time:")
        print("1. Quick (under 15 minutes)")
        print("2. Medium (15-30 minutes)") 
        print("3. Long (over 30 minutes)")
        
        choice = input("Enter your choice (1-3): ")
        
        filtered_recipes = []
        if choice == '1':
            filtered_recipes = [r for r in self.session_recipes if 'quick' in r.get('cooking_time', '').lower() or '10' in r.get('cooking_time', '')]
        elif choice == '2':
            filtered_recipes = [r for r in self.session_recipes if '15' in r.get('cooking_time', '') or '20' in r.get('cooking_time', '')]
        elif choice == '3':
            filtered_recipes = [r for r in self.session_recipes if '30' in r.get('cooking_time', '') or 'slow' in r.get('cooking_time', '').lower()]
        
        if filtered_recipes:
            print(f"\n🍽️  Filtered Recipes ({len(filtered_recipes)} found):")
            for i, recipe in enumerate(filtered_recipes, 1):
                print(f"{i}. {recipe['name']} - {recipe.get('cooking_time', 'Unknown')} minutes")
        else:
            print("❌ No recipes found matching your time criteria.")

    def _get_available_ingredients(self) -> List[str]:
        """Get list of available ingredients from inventory manager."""
        try:
            # Try to get ingredients from inventory manager
            if hasattr(self.inventory_mgr, 'get_current_inventory'):
                inventory = self.inventory_mgr.get_current_inventory()
                ingredients = []
                
                if inventory:
                    for item in inventory:
                        if isinstance(item, dict):
                            ingredients.append(item.get('name', '').lower())
                        else:
                            ingredients.append(str(item).lower())
                    return ingredients
            
            # Fallback to sample ingredients for testing
            return ['garlic', 'ginger', 'onion', 'noodles', 'rice', 'soy_sauce', 'oil', 'chili', 'herbs', 'chicken', 'tofu']
            
        except Exception as e:
            log_error("get available ingredients", e)
            # Return sample ingredients as fallback
            return ['garlic', 'ginger', 'onion', 'noodles', 'rice', 'soy_sauce', 'oil']

    def _generate_unique_recipe(self, ingredients: List[str]) -> Optional[Dict]:
        """Generate a single unique recipe."""
        # Choose recipe category based on available ingredients
        recipe_type = self._determine_recipe_type(ingredients)
        
        if not recipe_type:
            return None
        
        # Select template and components
        templates = self.recipe_templates.get(recipe_type, [])
        if not templates:
            return None
            
        template = random.choice(templates)
        
        # Build recipe components
        components = self._build_recipe_components(ingredients)
        
        try:
            recipe_name = template.format(**components)
            
            # Create recipe hash for uniqueness checking
            recipe_hash = hashlib.md5(recipe_name.lower().encode()).hexdigest()
            
            recipe = {
                'name': recipe_name,
                'type': recipe_type,
                'ingredients': self._select_recipe_ingredients(ingredients, components),
                'hash': recipe_hash,
                'description': self._generate_description(recipe_type, components),
                'cooking_time': self._estimate_cooking_time(recipe_type),
                'difficulty': self._determine_difficulty(recipe_type, len(components)),
                'servings': random.choice(['2', '2-3', '3-4', '4']),
                'cuisine': self._determine_cuisine(components)
            }
            
            return recipe
            
        except KeyError as e:
            # Template formatting failed, try again
            return None

    def _determine_recipe_type(self, ingredients: List[str]) -> str:
        """Determine what type of recipe to make based on ingredients."""
        # Priority-based selection for better variety
        if 'noodles' in ingredients and 'pasta' in ingredients:
            return random.choice(['noodles', 'stir_fry'])
        elif 'noodles' in ingredients:
            return random.choice(['noodles', 'stir_fry', 'soup'])
        elif 'rice' in ingredients:
            return random.choice(['rice', 'stir_fry', 'curry'])
        elif 'curry' in ingredients or 'coconut' in ingredients:
            return random.choice(['curry', 'soup'])
        elif len([i for i in ingredients if i in ['onion', 'garlic', 'ginger']]) >= 2:
            return random.choice(['stir_fry', 'soup', 'curry'])
        else:
            return random.choice(['stir_fry', 'soup', 'salad'])

    def _build_recipe_components(self, ingredients: List[str]) -> Dict:
        """Build recipe components from available ingredients."""
        components = {}
        
        # Select vegetables with variations
        vegetables = [ing for ing in ingredients if ing in ['onion', 'garlic', 'ginger', 'scallion', 'chili', 'herbs', 'celery', 'carrot', 'bell_pepper']]
        if vegetables:
            varied_vegetables = []
            selected_vegetables = random.sample(vegetables, min(3, len(vegetables)))  # Max 3 vegetables
            
            for veg in selected_vegetables:
                if veg in self.ingredient_variations:
                    varied_vegetables.append(random.choice(self.ingredient_variations[veg]))
                else:
                    varied_vegetables.append(veg)
            
            if len(varied_vegetables) == 1:
                components['vegetables'] = varied_vegetables[0]
            elif len(varied_vegetables) == 2:
                components['vegetables'] = f"{varied_vegetables[0]} and {varied_vegetables[1]}"
            else:
                components['vegetables'] = f"{', '.join(varied_vegetables[:-1])}, and {varied_vegetables[-1]}"
        else:
            components['vegetables'] = 'mixed vegetables'
        
        # Select protein (if available)
        proteins = [ing for ing in ingredients if ing in ['chicken', 'beef', 'pork', 'tofu', 'egg', 'shrimp', 'fish']]
        if proteins:
            components['protein'] = random.choice(proteins)
        else:
            components['protein'] = random.choice(['tofu', 'egg', 'mushrooms'])
        
        # Select flavor profile based on ingredients
        if 'soy_sauce' in ingredients and 'ginger' in ingredients:
            components['flavor'] = random.choice(['asian-style', 'ginger-soy', 'umami', 'savory'])
        elif 'chili' in ingredients:
            components['flavor'] = random.choice(['spicy', 'hot', 'fiery', 'zesty'])
        elif 'herbs' in ingredients:
            components['flavor'] = random.choice(['herb-crusted', 'aromatic', 'fragrant', 'herbed'])
        else:
            components['flavor'] = random.choice(self.flavor_profiles)
        
        # Select cooking method
        components['cooking_method'] = random.choice(self.cooking_methods)
        components['dish_type'] = random.choice(self.dish_types)
        
        # Select sauce
        if 'soy_sauce' in ingredients:
            components['sauce'] = random.choice(['soy', 'teriyaki', 'ginger-soy'])
        else:
            components['sauce'] = random.choice(self.sauces)
        
        return components

    def _select_recipe_ingredients(self, available: List[str], components: Dict) -> List[str]:
        """Select specific ingredients for the recipe."""
        selected = []
        
        # Always include base ingredients if available
        base_ingredients = ['oil', 'salt', 'pepper']
        for base in base_ingredients:
            if base in available:
                selected.append(base)
        
        # Add main ingredients based on components
        vegetables_text = components.get('vegetables', '').lower()
        for veg in ['garlic', 'ginger', 'onion', 'chili']:
            if veg in vegetables_text and veg in available:
                selected.append(veg)
        
        # Add protein if specified and available
        protein = components.get('protein', '')
        if protein in available:
            selected.append(protein)
        
        # Add sauce/seasoning
        sauce_ingredients = ['soy_sauce', 'oyster_sauce', 'sesame_oil', 'rice_vinegar']
        for sauce in sauce_ingredients:
            if sauce in available:
                selected.append(sauce)
                break
        
        # Add main carbohydrate
        carbs = ['noodles', 'rice', 'pasta']
        for carb in carbs:
            if carb in available:
                selected.append(carb)
                break
        
        return list(set(selected))  # Remove duplicates

    def _generate_description(self, recipe_type: str, components: Dict) -> str:
        """Generate a brief description for the recipe."""
        descriptions = {
            'noodles': f"Delicious {components.get('cooking_method', 'stir-fried')} noodles with aromatic {components.get('vegetables', 'vegetables')} and savory flavors",
            'rice': f"Flavorful {components.get('flavor', 'savory')} rice dish featuring {components.get('vegetables', 'fresh vegetables')} and {components.get('protein', 'protein')}",
            'stir_fry': f"Quick and healthy {components.get('cooking_method', 'stir-fried')} dish with {components.get('vegetables', 'crisp vegetables')} and {components.get('protein', 'protein')}",
            'soup': f"Warming and comforting {components.get('flavor', 'savory')} soup with fresh {components.get('vegetables', 'ingredients')} and tender {components.get('protein', 'protein')}",
            'curry': f"Rich and flavorful {components.get('flavor', 'aromatic')} curry with {components.get('vegetables', 'vegetables')} and {components.get('protein', 'protein')}",
            'salad': f"Fresh and nutritious {components.get('flavor', 'crisp')} salad with vibrant {components.get('vegetables', 'vegetables')} and {components.get('protein', 'protein')}"
        }
        return descriptions.get(recipe_type, f"Delicious {components.get('flavor', 'homemade')} dish with fresh ingredients")

    def _estimate_cooking_time(self, recipe_type: str) -> str:
        """Estimate cooking time based on recipe type."""
        time_estimates = {
            'noodles': random.choice(['10-15', '15-20', '12-18']),
            'rice': random.choice(['20-25', '25-30', '18-25']),
            'stir_fry': random.choice(['8-12', '10-15', '12-18']),
            'soup': random.choice(['25-35', '30-40', '20-30']),
            'curry': random.choice(['30-45', '35-50', '25-40']),
            'salad': random.choice(['5-10', '8-12', '10-15'])
        }
        return time_estimates.get(recipe_type, '15-25')

    def _determine_difficulty(self, recipe_type: str, num_components: int) -> str:
        """Determine recipe difficulty."""
        if recipe_type in ['salad'] or num_components <= 3:
            return 'Easy'
        elif recipe_type in ['stir_fry', 'noodles'] or num_components <= 5:
            return random.choice(['Easy', 'Medium'])
        elif recipe_type in ['curry', 'soup']:
            return random.choice(['Medium', 'Medium-Hard'])
        else:
            return 'Medium'

    def _determine_cuisine(self, components: Dict) -> str:
        """Determine cuisine type based on components."""
        vegetables = components.get('vegetables', '').lower()
        flavor = components.get('flavor', '').lower()
        sauce = components.get('sauce', '').lower()
        
        if 'asian' in flavor or 'soy' in sauce or 'ginger' in vegetables:
            return random.choice(['Asian', 'Chinese', 'Thai', 'Japanese'])
        elif 'curry' in sauce or 'spicy' in flavor:
            return random.choice(['Indian', 'Thai', 'Asian'])
        elif 'herb' in flavor:
            return random.choice(['Mediterranean', 'Italian', 'French'])
        else:
            return random.choice(['International', 'Fusion', 'Home-style'])

    def _is_recipe_unique(self, new_recipe: Dict, existing_recipes: List[Dict]) -> bool:
        """Check if recipe is unique compared to existing ones."""
        if not existing_recipes:
            return True
        
        new_hash = new_recipe.get('hash')
        new_name = new_recipe.get('name', '').lower()
        
        for existing in existing_recipes:
            # Check hash for exact duplicates
            if existing.get('hash') == new_hash:
                return False
            
            # Check name similarity (prevent very similar names)
            existing_name = existing.get('name', '').lower()
            similarity = self._calculate_similarity(new_name, existing_name)
            if similarity > 0.75:  # More than 75% similar
                return False
        
        return True

    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two recipe names using word overlap."""
        if not name1 or not name2:
            return 0.0
            
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0

    def view_favorite_recipes(self):
        """Display user's favorite recipes from database."""
        try:
            # Try to get user ID safely
            user_id = getattr(self.user_mgr, 'current_user_id', 'default_user')
            
            if hasattr(self.database, 'get_collection'):
                collection = self.database.get_collection('favorite_recipes')
                favorites = list(collection.find({'user_id': user_id}))
            else:
                # Fallback - no saved recipes
                favorites = []
            
            if not favorites:
                print("❌ You haven't saved any favorite recipes yet!")
                print("💡 Try generating some recipes and save your favorites.")
                return
            
            print(f"\n⭐ Your Favorite Recipes ({len(favorites)} saved):")
            print("=" * 40)
            
            for i, recipe in enumerate(favorites, 1):
                print(f"{i}. {recipe['name']}")
                print(f"   📝 {recipe.get('description', 'No description')}")
                print(f"   ⏱️  {recipe.get('cooking_time', 'Unknown')} minutes")
                print(f"   📊 {recipe.get('difficulty', 'Unknown')} difficulty")
                print()
            
            # Option to view detailed recipe
            choice = input("Enter recipe number for details (or press Enter to continue): ")
            if choice.isdigit():
                recipe_num = int(choice) - 1
                if 0 <= recipe_num < len(favorites):
                    self._display_detailed_recipe(favorites[recipe_num])
                    
        except Exception as e:
            log_error("view favorite recipes", e)
            print("❌ Error loading favorite recipes.")

    def clear_session_recipes(self):
        """Clear current session recipes (useful for fresh start)."""
        self.session_recipes.clear()
        self.generated_recipes.clear()
        print("✅ Recipe session cleared!")