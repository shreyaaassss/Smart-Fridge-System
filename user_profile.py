import os
import getpass
from datetime import datetime
from typing import Optional, Dict, Any, List
from bcrypt import hashpw, gensalt, checkpw
from database import DatabaseStateMachine , DatabaseConnectionContext
from database import DatabaseConnectionError
from constants import (
    DIET_OPTIONS, ALLERGY_OPTIONS, CUISINE_OPTIONS, 
    PROTEIN_OPTIONS, AGE_GROUP_OPTIONS, CULTURAL_RESTRICTIONS
)
from utils import (
    log_error, safe_db_call, get_multiple_choice, 
    input_with_default
)


class UserProfileManager:
    """Handles user authentication and profile management."""
    def __init__(self, database: DatabaseStateMachine):
        self.database = database
        self.current_user = None
        self.current_profile = None

    def login_or_register(self) -> bool:
        """Handle user login or registration."""
        print("\nSmart Fridge Login")
        print("1. Login")
        print("2. Register")
        print("0. Exit")
       
        choice = input("\nEnter your choice (0-2): ")
       
        if choice == '1':
            return self._login()
        elif choice == '2':
            return self._register()
        elif choice == '0':
            return False
        else:
            print("Invalid choice. Please try again.")
            return self.login_or_register()

    def _login(self) -> bool:
        """Authenticate user."""
        print("\nLogin")
        
        username = input("Username: ")
        password = getpass.getpass("Password: ")
       
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                user = db['users'].find_one({"username": username})
               
                if user and checkpw(password.encode('utf-8'), user['password']):
                    self.current_user = user
                    self.current_profile = user.get('profile', {})
                    print(f"\nWelcome back, {username}!")
                    return True
                else:
                    print("\nInvalid username or password")
                    return False
        except Exception as e:
            log_error("user login", e)
            return False

    def _register(self) -> bool:
        """Register new user with comprehensive profile."""
        print("\nNew User Registration")
        
        username = input("Choose a username: ")
       
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                if db['users'].find_one({"username": username}):
                    print("\nUsername already exists")
                    return False
               
                password = getpass.getpass("Choose a password: ")
                confirm_password = getpass.getpass("Confirm password: ")
               
                if password != confirm_password:
                    print("\nPasswords don't match")
                    return False
               
                hashed_pw = hashpw(password.encode('utf-8'), gensalt())
               
                # Collect profile information using helper functions
                print("\nHousehold Information")
               
                household_size = int(input_with_default(
                    "Number of people in the household (1-10)",
                    "1"
                ))
               
                age_groups = get_multiple_choice(
                    "Age groups",
                    AGE_GROUP_OPTIONS
                )
               
                cooking_freq = input_with_default(
                    "Cooking frequency:\n1. Daily\n2. Batch cooking\n3. Mixed",
                    "3"
                )
                cooking_freq = {"1": "Daily", "2": "Batch", "3": "Mixed"}.get(cooking_freq, "Mixed")
               
                shopping_freq = input_with_default(
                    "Grocery shopping frequency:\n1. Weekly\n2. Bi-weekly\n3. Monthly",
                    "1"
                )
                shopping_freq = {"1": "Weekly", "2": "Bi-weekly", "3": "Monthly"}.get(shopping_freq, "Weekly")
               
                print("\nDietary Preferences & Restrictions")
               
                diet_types = get_multiple_choice(
                    "Diet types",
                    DIET_OPTIONS
                )
               
                allergies = get_multiple_choice(
                    "Food allergies",
                    ALLERGY_OPTIONS
                )
               
                cultural_restrictions = get_multiple_choice(
                    "Cultural restrictions",
                    CULTURAL_RESTRICTIONS
                )
               
                cuisines = get_multiple_choice(
                    "Preferred cuisines",
                    CUISINE_OPTIONS
                )
               
                meal_freq = input_with_default(
                    "Meal frequency:\n1. 3 main meals\n2. 3 meals + snacks\n3. 6 smaller meals",
                    "1"
                )
                meal_frequency = {"1": 3, "2": 4, "3": 6}.get(meal_freq, 3)
               
                proteins = get_multiple_choice(
                    "Preferred proteins",
                    PROTEIN_OPTIONS
                )
               
                budget = input_with_default(
                    "Budget level:\n1. Low\n2. Medium\n3. High",
                    "2"
                )
                budget = {"1": "low", "2": "medium", "3": "high"}.get(budget, "medium")
               
                profile = {
                    "username": username,
                    "password": hashed_pw,
                    "created_at": datetime.now(),
                    "profile": {
                        "household_size": household_size,
                        "age_groups": age_groups,
                        "cooking_frequency": cooking_freq,
                        "shopping_frequency": shopping_freq,
                        "diet_types": diet_types,
                        "allergies": allergies,
                        "cultural_restrictions": cultural_restrictions,
                        "cuisine_preferences": cuisines,
                        "meal_frequency": meal_frequency,
                        "preferred_proteins": proteins,
                        "budget": budget
                    },
                    "inventory": [],
                    "recipes": [],
                    "grocery_lists": [],
                    "consumption_history": []
                }
               
                db['users'].insert_one(profile)
                print(f"\nRegistration successful! Welcome {username}")
                self.current_user = profile
                self.current_profile = profile.get('profile', {})
                return True
        except Exception as e:
            log_error("user registration", e)
            return False

    def view_profile(self) -> None:
        """Display current user profile."""
        if not self.current_user:
            print("\nNo user logged in")
            return
           
        profile = self.current_profile
       
        print(f"\n{self.current_user['username']}'s Profile")
        
        # Household Information
        print("\nHousehold:")
        print(f"Size: {profile.get('household_size', 1)}")
        print(f"Age Groups: {', '.join(profile.get('age_groups', [])) or 'None'}")
        print(f"Cooking: {profile.get('cooking_frequency', 'Not specified')}")
        print(f"Shopping: {profile.get('shopping_frequency', 'Not specified')}")
       
        # Dietary Restrictions
        print("\nDietary:")
        print(f"Diets: {', '.join(profile.get('diet_types', [])) or 'None'}")
        print(f"Allergies: {', '.join(profile.get('allergies', [])) or 'None'}")
        print(f"Cultural: {', '.join(profile.get('cultural_restrictions', [])) or 'None'}")
       
        # Cuisine Preferences
        print("\nCuisines:")
        print(f"Preferred Cuisines: {', '.join(profile.get('cuisine_preferences', [])) or 'None'}")
       
        # Preferences
        print("\nPreferences:")
        print(f"Meals/Day: {profile.get('meal_frequency', 3)}")
        print(f"Proteins: {', '.join(profile.get('preferred_proteins', [])) or 'None'}")
        print(f"Budget: {profile.get('budget', 'medium').capitalize()}")

    def edit_profile(self) -> None:
        """Edit user profile with comprehensive options."""
        if not self.current_user:
            print("\nNo user logged in")
            return
           
        self.view_profile()
        
        print("\nEdit Profile")
        print("1. Household Information")
        print("2. Dietary Restrictions")
        print("3. Cuisine Preferences")
        print("4. Meal Preferences")
        print("0. Back to Main Menu")
       
        choice = input("\nWhat would you like to edit? (0-4): ")
       
        try:
            if choice == '1':
                self._edit_household_info()
            elif choice == '2':
                self._edit_dietary_restrictions()
            elif choice == '3':
                self._edit_cuisine_preferences()
            elif choice == '4':
                self._edit_meal_preferences()
            elif choice == '0':
                return
            else:
                print("\nInvalid choice")
                return
               
            print("\nProfile updated successfully!")
        except Exception as e:
            log_error("profile edit", e)

    def _edit_household_info(self) -> None:
        """Edit household information section."""
        print("\nEdit Household Info")
       
        # Update household size
        new_size = input_with_default(
            f"Household size (current: {self.current_profile.get('household_size', 1)})",
            str(self.current_profile.get('household_size', 1))
        )
        if new_size:
            try:
                new_size = int(new_size)
                if 1 <= new_size <= 10:
                    self.current_profile['household_size'] = new_size
                    self._update_profile_field('household_size', new_size)
                else:
                    print("\nHousehold size must be between 1 and 10")
            except ValueError:
                print("\nPlease enter a valid number")
       
        # Update age groups
        age_groups = get_multiple_choice(
            f"Age groups (current: {', '.join(self.current_profile.get('age_groups', []))}",
            AGE_GROUP_OPTIONS
        )
        if age_groups is not None:
            self.current_profile['age_groups'] = age_groups
            self._update_profile_field('age_groups', age_groups)

    def _edit_dietary_restrictions(self) -> None:
        """Edit dietary restrictions section."""
        print("\nEdit Dietary Restrictions")
       
        # Update diet types
        diet_types = get_multiple_choice(
            f"Diet types (current: {', '.join(self.current_profile.get('diet_types', []))}",
            DIET_OPTIONS
        )
        if diet_types is not None:
            self.current_profile['diet_types'] = diet_types
            self._update_profile_field('diet_types', diet_types)
       
        # Update allergies
        allergies = get_multiple_choice(
            f"Allergies (current: {', '.join(self.current_profile.get('allergies', []))}",
            ALLERGY_OPTIONS
        )
        if allergies is not None:
            self.current_profile['allergies'] = allergies
            self._update_profile_field('allergies', allergies)

    def _edit_cuisine_preferences(self) -> None:
        """Edit cuisine preferences section."""
        print("\nEdit Cuisine Preferences")
       
        cuisines = get_multiple_choice(
            f"Preferred cuisines (current: {', '.join(self.current_profile.get('cuisine_preferences', []))}",
            CUISINE_OPTIONS
        )
        if cuisines is not None:
            self.current_profile['cuisine_preferences'] = cuisines
            self._update_profile_field('cuisine_preferences', cuisines)

    def _edit_meal_preferences(self) -> None:
        """Edit meal preferences section."""
        print("\nEdit Meal Preferences")
       
        # Update meal frequency
        meal_freq = input_with_default(
            f"Meal frequency (current: {self.current_profile.get('meal_frequency', 3)}):\n"
            "1. 3 main meals\n2. 3 meals + snacks\n3. 6 smaller meals",
            str(self.current_profile.get('meal_frequency', 3))
        )
        if meal_freq:
            new_freq = {"1": 3, "2": 4, "3": 6}.get(meal_freq, 3)
            self.current_profile['meal_frequency'] = new_freq
            self._update_profile_field('meal_frequency', new_freq)
       
        # Update proteins
        proteins = get_multiple_choice(
            f"Preferred proteins (current: {', '.join(self.current_profile.get('preferred_proteins', []))}",
            PROTEIN_OPTIONS
        )
        if proteins is not None:
            self.current_profile['preferred_proteins'] = proteins
            self._update_profile_field('preferred_proteins', proteins)
       
        # Update budget
        budget = input_with_default(
            f"Budget level (current: {self.current_profile.get('budget', 'medium')}):\n"
            "1. Low\n2. Medium\n3. High",
            {"low": "1", "medium": "2", "high": "3"}.get(self.current_profile.get('budget', 'medium'), "2")
        )
        if budget:
            new_budget = {"1": "low", "2": "medium", "3": "high"}.get(budget, "medium")
            self.current_profile['budget'] = new_budget
            self._update_profile_field('budget', new_budget)

    def _update_profile_field(self, field: str, value: Any) -> None:
        """Helper to update a single profile field in the database."""
        safe_db_call(
            f"update profile field {field}",
            lambda: self.database.get_client()['users'].update_one(
                {"username": self.current_user['username']},
                {"$set": {f"profile.{field}": value}}
            )
        )