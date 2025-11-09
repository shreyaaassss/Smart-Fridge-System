import os
import re
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Optional
from PIL import Image
import google.generativeai as genai
from constants import GEMINI_API_KEY
from constants import (
    INVENTORY_PROMPT_TEMPLATE, RECIPE_PROMPT_TEMPLATE,
    INGREDIENT_SYNONYMS, COMMON_ALLERGENS
)
from utils import log_error, is_cache_valid

class VisionService:
    """Handles all AI vision-related operations."""
    def __init__(self, cache_dir="./cache"):
        self.cache_dir = cache_dir
        self.ai_cache = {}
        self.model = None
        self._setup_gemini()

    def _setup_gemini(self) -> None:
        """Configure Gemini AI with API key."""
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("\nGemini AI configured successfully!")
        except Exception as e:
            log_error("Gemini AI setup", e)
            self.model = None

    def get_cached_response(self, image_path: str, mode: str) -> Optional[str]:
        try:
            with open(image_path, 'rb') as f:
                image_hash = hashlib.md5(f.read()).hexdigest()
               
            cache_key = f"{image_hash}_{mode}"
           
            # Check memory cache first
            if cache_key in self.ai_cache:
                print("\nUsing cached AI response...")
                return self.ai_cache[cache_key]
               
            # Check disk cache
            cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    if is_cache_valid(data['timestamp']):
                        print("\nUsing disk-cached AI response...")
                        self.ai_cache[cache_key] = data['response']
                        return data['response']
                    else:
                        os.remove(cache_file)  # Remove stale cache
           
            return None
        except Exception as e:
            log_error("cache retrieval", e)
            return None

    def cache_response(self, image_path: str, mode: str, response: str) -> None:
        try:
            with open(image_path, 'rb') as f:
                image_hash = hashlib.md5(f.read()).hexdigest()
            cache_key = f"{image_hash}_{mode}"

            # Update memory cache
            self.ai_cache[cache_key] = response

            # Update disk cache
            cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
            with open(cache_file, 'w') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "response": response,
                    "mode": mode
                }, f)
        except Exception as e:
            log_error("cache storage", e)

    def analyze_inventory(self, image_path: str) -> Optional[str]:
        """Analyze image to detect food inventory."""
        if not self.model:
            print("\nGemini AI not configured properly")
            return None
           
        cached_response = self.get_cached_response(image_path, 'items')
        if cached_response:
            return cached_response
           
        try:
            print("\nGenerating AI analysis...")
            response = self.model.generate_content([INVENTORY_PROMPT_TEMPLATE, Image.open(image_path)])
           
            self.cache_response(image_path, 'items', response.text)
           
            return response.text
           
        except Exception as e:
            log_error("AI inventory analysis", e)
            return None

    def generate_recipes(self, inventory_text: str) -> Optional[str]:
        """Generate recipes based on inventory."""
        if not self.model:
            print("\nGemini AI not configured properly")
            return None
           
        try:
            print("\nGenerating recipe suggestions...")
            response = self.model.generate_content([RECIPE_PROMPT_TEMPLATE, inventory_text])
           
            return response.text
           
        except Exception as e:
            log_error("recipe generation", e)
            return None

    def check_allergy_risk(self, item_name: str, user_allergies: List[str]) -> bool:
        """Check if an item poses allergy risk for the user."""
        if not user_allergies:
            return False
           
        item_name = self.normalize_ingredient_name(item_name)
       
        for allergy in user_allergies:
            allergy = allergy.lower()
            if allergy in COMMON_ALLERGENS:
                for allergen in COMMON_ALLERGENS[allergy]:
                    if allergen in item_name:
                        return True
            elif allergy in item_name:
                return True
               
        return False

    def parse_inventory(self, items_text: str) -> List[Dict]:
        """Parse detected items text into structured format."""
        parsed_items = []
        current_category = None
        lines = items_text.split('\n')
       
        for line in lines:
            line = line.strip()
            if not line:
                continue
           
            if ':' in line and not line.startswith('-'):
                current_category = line.rstrip(':')
                continue
               
            if line.startswith('-') and current_category:
                item_info = {'category': current_category}
               
                item_text = line[1:].strip()
               
                if '(x' in item_text:
                    item_name, quantity_str = item_text.split('(x')
                    item_info['name'] = self.normalize_ingredient_name(item_name.strip())
                    item_info['quantity'] = quantity_str.rstrip(')')
                elif '(' in item_text and ')' in item_text:
                    parts = item_text.split('(')
                    item_info['name'] = self.normalize_ingredient_name(parts[0].strip())
                    item_info['notes'] = parts[1].rstrip(')')
                else:
                    item_info['name'] = self.normalize_ingredient_name(item_text)
               
                item_info['timestamp'] = datetime.now()
               
                parsed_items.append(item_info)
       
        return parsed_items

    def parse_recipes(self, recipes_text: str) -> List[Dict]:
        """Improved recipe parser that strictly follows our format."""
        recipes = []
        current_recipe = None
        sections = [
            'description', 'cuisine', 'dietary_tags', 'ingredients',
            'instructions', 'prep_time', 'cook_time', 'total_time',
            'servings', 'difficulty'
        ]
        
        for line in recipes_text.strip().split('\n'):
            line = line.strip()
            
            # Skip empty lines between recipes but not within recipes
            if not line:
                if current_recipe and current_recipe.get('name'):
                    continue
                else:
                    if current_recipe and current_recipe.get('name'):
                        recipes.append(current_recipe)
                        current_recipe = None
                    continue
            
            # Recipe title detection
            if line.startswith(('### Recipe:', '###Recipe:')):
                if current_recipe and current_recipe.get('name'):
                    recipes.append(current_recipe)
                title = line.split(':', 1)[1].strip() if ':' in line else line.split(' ', 2)[2].strip()
                current_recipe = {
                    'name': title,
                    'title': title,
                    'description': '',
                    'cuisine': '',
                    'dietary_tags': [],
                    'ingredients': [],
                    'instructions': [],
                    'prep_time': '',
                    'cook_time': '',
                    'total_time': '',
                    'servings': '',
                    'difficulty': ''
                }
            
            # Section detection
            elif line.startswith('#### '):
                section = line[5:].lower().replace(' ', '_').rstrip(':')
                current_section = section
            
            # Content parsing
            elif current_recipe:
                if line.startswith('-') and current_section == 'ingredients':
                    current_recipe['ingredients'].append(line[1:].strip())
                elif line[0].isdigit() and line[1] in ('.', ')') and current_section == 'instructions':
                    step = line.split('.', 1)[1].strip() if '.' in line else line.split(')', 1)[1].strip()
                    current_recipe['instructions'].append(step)
                elif current_section == 'time' and ':' in line:
                    if 'prep' in line.lower():
                        current_recipe['prep_time'] = line.split(':', 1)[1].strip()
                    elif 'cook' in line.lower():
                        current_recipe['cook_time'] = line.split(':', 1)[1].strip()
                    elif 'total' in line.lower():
                        current_recipe['total_time'] = line.split(':', 1)[1].strip()
                elif current_section == 'serving' and ':' in line:
                    if 'servings' in line.lower():
                        current_recipe['servings'] = line.split(':', 1)[1].strip()
                    elif 'difficulty' in line.lower():
                        current_recipe['difficulty'] = line.split(':', 1)[1].strip()
                elif not current_section and current_recipe['description'] == '':
                    current_recipe['description'] = line
        
        # Add the last recipe if exists
        if current_recipe and current_recipe.get('name'):
            recipes.append(current_recipe)
        
        # Filter out any empty recipes
        recipes = [r for r in recipes if r.get('name')]
        
        return recipes
       
    def normalize_ingredient_name(self, name: str) -> str:
        """Normalize ingredient names using regex patterns."""
        if not name:
            return ""
           
        name = name.lower().strip()
       
        # Remove quantity descriptors and units
        name = re.sub(r'\b\d+\s*(kg|g|ml|l|oz|lb|pound|ounce|liter|gram|kilo)\b', '', name)
        name = re.sub(r'\b(pieces?|chopped|halves|whole|sliced|diced|minced|grated)\b', '', name)
       
        # Remove parenthetical quantities and notes
        name = re.sub(r'\(.*?\)', '', name)
       
        # Remove special characters except hyphens between words
        name = re.sub(r'[^\w\s-]', '', name)
       
        # Clean up whitespace
        name = re.sub(r'\s+', ' ', name).strip()
       
        # Apply synonym mapping
        for original, synonym in INGREDIENT_SYNONYMS.items():
            if original in name:
                name = name.replace(original, synonym)
                break
       
        return name