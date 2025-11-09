# Updated main.py
import logging
from database import DatabaseStateMachine, DatabaseConnectionContext, ConnectionStatus, DatabaseConnectionError
from user_profile import UserProfileManager
from camera_service import CameraService
from vision_service import VisionService
from inventory_manager import InventoryManager
from recipe_manager import RecipeManager
from constants import MONGO_URI, CACHE_DIR
from utils import log_error
import pymongo

class SmartFridgeSystem:
    """Main system class that orchestrates all components."""
    def __init__(self):
        self._setup_database()
        self.vision_service = VisionService()
        self.user_mgr = UserProfileManager(self.database)
        self.camera_service = CameraService(self.database)
        self.inventory_mgr = InventoryManager(self.database, self.vision_service, self.user_mgr)
        self.recipe_mgr = RecipeManager(self.database, self.inventory_mgr, self.vision_service, self.user_mgr)

    def _setup_database(self) -> None:
        """Configure database connection with SSL/TLS support."""
        try:
            # Configure database connection factory
            def create_connection():
                import certifi
                ca = certifi.where()
                
                return pymongo.MongoClient(
                    MONGO_URI,
                    tlsCAFile=ca,
                    connectTimeoutMS=10000,
                    socketTimeoutMS=30000,
                    serverSelectionTimeoutMS=10000,
                    retryWrites=True,
                    retryReads=True,
                    tlsAllowInvalidCertificates=False
                )
            
            self.database = DatabaseStateMachine(create_connection)
            self.database.connect()
            
        except Exception as e:
            log_error("database setup", e)
            raise
                
    def run(self) -> None:
        """Main application loop."""
        try:
            if not self.user_mgr.login_or_register():
                return
        
            while True:
                self._display_main_menu()
                choice = input("\nEnter your choice (0-11): ")
            
                if choice == '1':
                    self.inventory_mgr.scan_fridge(self.camera_service)
                elif choice == '2':
                    self.inventory_mgr.display_inventory()
                elif choice == '3':
                    self.inventory_mgr.add_item_manually()
                elif choice == '4':
                    self.inventory_mgr.edit_item()
                elif choice == '5':
                    self.inventory_mgr.remove_item()
                elif choice == '6':
                    self.recipe_mgr.suggest_recipes()
                elif choice == '7':
                    self.recipe_mgr.view_favorite_recipes()
                elif choice == '8':
                    self.inventory_mgr.generate_grocery_list()
                elif choice == '9':
                    self.inventory_mgr.view_grocery_lists()  # New function
                elif choice == '10':
                    self.user_mgr.view_profile()
                elif choice == '11':
                    self.user_mgr.edit_profile()
                elif choice == '0':
                    print("\nGoodbye!")
                    break
                else:
                    print("\nInvalid choice. Please try again.")
        except Exception as e:
            log_error("main application", e)
        finally:
            if hasattr(self, 'database') and self.database.status == ConnectionStatus.CONNECTED:
                self.database.get_client().close()

    def _display_main_menu(self) -> None:
        """Display the main menu."""
        print("\nSmart Fridge System")
        print("=" * 20)
        print("1. Scan Fridge Contents")
        print("2. View Current Inventory")
        print("3. Add Item Manually")
        print("4. Edit Inventory Item")
        print("5. Remove Item from Inventory")
        print("6. Get Recipe Suggestions")
        print("7. View Favorite Recipes")
        print("8. Generate/Manage Grocery List")
        print("9. View Saved Grocery Lists")  # New option
        print("10. View User Profile")
        print("11. Edit User Profile")
        print("0. Exit")

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        filename='smart_fridge.log',
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
   
    # Run the application
    app = SmartFridgeSystem()
    app.run()