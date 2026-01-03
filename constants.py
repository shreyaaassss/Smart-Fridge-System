# ========== GLOBAL CONSTANTS ==========
MONGO_URI = ""
GEMINI_API_KEY = ""
CACHE_DIR = "./cache"
DEFAULT_SERVER_URL = "http://172.16.1.252:5000"

# ========== STATIC CONFIGURATIONS ==========
DIET_OPTIONS = {
    '1': 'Vegan',
    '2': 'Vegetarian',
    '3': 'Non-Vegetarian',
    '4': 'Gluten-Free',
    '5': 'Keto/Low Carb'
}

ALLERGY_OPTIONS = {
    '1': 'Dairy',
    '2': 'Gluten',
    '3': 'Nuts',
    '4': 'Soy',
    '5': 'Seafood'
}

CUISINE_OPTIONS = {
    '1': 'Indian',
    '2': 'Continental',
    '3': 'Chinese',
    '4': 'Italian',
    '5': 'Mexican'
}

PROTEIN_OPTIONS = {
    '1': 'Lentils',
    '2': 'Paneer',
    '3': 'Tofu',
    '4': 'Eggs',
    '5': 'Meat'
}

AGE_GROUP_OPTIONS = {
    '1': 'Children',
    '2': 'Teens',
    '3': 'Adults',
    '4': 'Seniors'
}

CULTURAL_RESTRICTIONS = {
    '1': 'No Beef',
    '2': 'No Pork',
    '3': 'Halal',
    '4': 'Jain'
}

INGREDIENT_SYNONYMS = {
    'chickpeas': 'garbanzo beans',
    'aubergine': 'eggplant',
    'courgette': 'zucchini',
    'capsicum': 'bell pepper',
    'spring onion': 'green onion',
    'coriander': 'cilantro',
}

COMMON_ALLERGENS = {
    'dairy': ['milk', 'cheese', 'butter', 'cream', 'yogurt'],
    'gluten': ['wheat', 'barley', 'rye', 'bread', 'pasta', 'flour'],
    'nuts': ['almond', 'peanut', 'cashew', 'walnut', 'hazelnut'],
    'soy': ['soy', 'tofu', 'soybean', 'soya'],
    'seafood': ['fish', 'shrimp', 'prawn', 'crab', 'lobster', 'shellfish']
}

INVENTORY_PROMPT_TEMPLATE = """
Analyze this refrigerator/kitchen image and list all food items you can identify.
Organize them by category (Fruits, Vegetables, Dairy, Meats, Beverages, Condiments, etc.).
For each item, include approximate quantity if visible (e.g. x2, half full).
Format as:

Category:
- Item (quantity or notes)
- Item (quantity or notes)

Next Category:
- etc.
"""

RECIPE_PROMPT_TEMPLATE = """
Generate exactly 3 {cuisine} cuisine recipes based on available ingredients.
Follow this EXACT structure for each recipe:

### Recipe: [Recipe Name]
[Short Description - 1-2 lines]

#### Cuisine: 
{cuisine}

#### Dietary Tags:
[Vegetarian/Vegan/Gluten-free/etc.]

#### Ingredients:
- [Ingredient 1] [Quantity]
- [Ingredient 2] [Quantity]
- [Available ingredients marked with *]

#### Instructions:
1. [Step 1]
2. [Step 2]
3. [Step 3]

#### Time:
- Prep: [X minutes]
- Cook: [X minutes]
- Total: [X minutes]

#### Serving:
- Servings: [X]
- Difficulty: [Easy/Medium/Hard]

Available ingredients:
{inventory}

Important Notes:
1. Use this exact structure for all 3 recipes
2. Separate recipes with 2 blank lines
3. Include quantities for all ingredients
4. Mark available ingredients with *
5. Number all instruction steps
"""
