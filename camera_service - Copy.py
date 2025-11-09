import os
import socket
import time
import requests
from datetime import datetime
from typing import Optional, Dict
from database import DatabaseStateMachine
from database import DatabaseConnectionContext
from utils import log_error
from constants import DEFAULT_SERVER_URL, CACHE_DIR
class DatabaseConnectionContext:
    """Context manager for database connections."""
    def __init__(self, client, db_name: str = "SmartKitchen"):
        self._client = client
        self._db_name = db_name
        self._connection = None

    def __enter__(self):
        self._connection = self._client[self._db_name]
        return self._connection

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class CameraService:
    """Handles all camera-related operations."""
    def __init__(self, database: DatabaseStateMachine, server_url=None, cache_dir=CACHE_DIR):
        self.database = database
        self.server_url = server_url or self._get_stored_server_url() or DEFAULT_SERVER_URL
        self.connection_status = False
        self.last_check_time = None
        self.cache_dir = cache_dir
       
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(os.path.join(cache_dir, "images"), exist_ok=True)

    def _get_stored_server_url(self) -> Optional[str]:
        """Retrieve stored server URL from MongoDB."""
        try:
            with DatabaseConnectionContext(self.database.get_client()) as db:
                config = db['system_config'].find_one({"config_type": "server_url"})
                if config and 'public_url' in config:
                    return config['public_url']
        except Exception as e:
            log_error("fetching server URL", e)
        return None

    def update_server_url(self) -> None:
        """Update the Raspberry Pi URL."""
        print(f"\nCurrent Raspberry Pi URL: {self.server_url}")
        new_url = input("Enter new URL (e.g., http://172.16.1.200:5000): ")
        if new_url:
            self.server_url = new_url
            try:
                with DatabaseConnectionContext(self.database.get_client()) as db:
                    db['system_config'].update_one(
                        {"config_type": "server_url"},
                        {"$set": {"public_url": new_url, "last_updated": datetime.now()}},
                        upsert=True
                    )
            except Exception as e:
                log_error("saving server URL", e)
            
            print(f"\nUpdated URL to {new_url}")
            self.check_connection(force=True)   

    def check_connection(self, force=False) -> bool:
        """Test connectivity to the Raspberry Pi server."""
        current_time = datetime.now()
        if not force and self.last_check_time and (current_time - self.last_check_time).seconds < 60:
            return self.connection_status
       
        try:
            print(f"\nTesting connection to {self.server_url}...")
           
            try:
                response = requests.get(f"{self.server_url}/test", timeout=3)
                if response.status_code == 200:
                    self.connection_status = True
                    self.last_check_time = current_time
                    print("\nConnection to Raspberry Pi successful!")
                    return True
            except:
                pass
               
            url_parts = self.server_url.split(":")
            if len(url_parts) >= 2:
                hostname = url_parts[1].strip("/")
                port = int(url_parts[2].split("/")[0]) if len(url_parts) > 2 else 80
               
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                result = s.connect_ex((hostname, port))
                s.close()
               
                self.connection_status = (result == 0)
                self.last_check_time = current_time
               
                if self.connection_status:
                    print("\nPort is open and reachable!")
                else:
                    print(f"\nPort {port} is not open on {hostname}")
               
                return self.connection_status
            else:
                print("\nInvalid URL format")
                self.connection_status = False
                self.last_check_time = current_time
                return False
               
        except Exception as e:
            self.connection_status = False
            self.last_check_time = current_time
            log_error("camera connection check", e)
            return False

    def capture_image(self) -> Optional[Dict]:
        """Request the Raspberry Pi to capture an image and return metadata."""
        if not self.check_connection():
            print("\nWould you like to update the Raspberry Pi URL? (y/n)")
            if input().lower().startswith('y'):
                self.update_server_url()
                return self.capture_image()
            return None
               
        try:
            endpoint = "/capture"
            print(f"\nRequesting image capture from {self.server_url}{endpoint}...")
           
            headers = {
                "Accept": "application/json",
                "User-Agent": "SmartFridgeSystem/2.0"
            }
           
            response = requests.get(
                f"{self.server_url}{endpoint}",
                timeout=15,
                headers=headers
            )
           
            if response.status_code == 200:
                result = response.json()
                if 'image_id' in result:
                    print(f"\nImage captured with ID: {result['image_id']}")
                    return result
                else:
                    print("\nImage captured successfully!")
                    return result
            else:
                print(f"\nFailed to request image capture. Status code: {response.status_code}")
                print(f"Response: {response.text[:200]}...")
                return None
               
        except requests.exceptions.ConnectionError:
            print("\nConnection refused. Is the camera service running?")
            return None
        except requests.exceptions.Timeout:
            print("\nConnection timed out. The server is taking too long to respond.")
            return None
        except Exception as e:
            log_error("image capture", e)
            return None

    def get_latest_image(self, retries=3, delay=2) -> Optional[str]:
        """Retrieve the latest image from the server with retry mechanism."""
        for attempt in range(retries):
            if not self.check_connection():
                return None

            try:
                print(f"\nAttempt {attempt + 1}: Retrieving latest image...")
                response = requests.get(f"{self.server_url}/latest_image", timeout=15, stream=True)
                if response.status_code == 200:
                    temp_filename = f"latest_img_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    temp_path = os.path.join(self.cache_dir, "images", temp_filename)

                    with open(temp_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)

                    return temp_path
                else:
                    print(f"\nFailed (Status: {response.status_code}). Retrying...")
            except Exception as e:
                print(f"\nError: {str(e)}. Retrying...")

            time.sleep(delay)

        print("\nFailed to retrieve image after multiple attempts.")
        return None

    def preprocess_image(self, image_path: str) -> str:
        """Preprocess image for better AI analysis results."""
        try:
            from PIL import Image, ImageOps
            img = Image.open(image_path)
           
            # Resize and compress image
            max_size = 800
            quality = 85
           
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size))
           
            enhanced_img = ImageOps.autocontrast(img, cutoff=2)
           
            preprocessed_path = image_path.replace('.jpg', '_processed.jpg')
           
            # Save with optimized quality
            enhanced_img.save(preprocessed_path, quality=quality, optimize=True)
           
            return preprocessed_path
        except Exception as e:
            log_error("image preprocessing", e)
            print("\nImage preprocessing failed. Using original image.")
            return image_path