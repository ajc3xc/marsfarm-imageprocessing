#!/usr/bin/env python3
import os, sys, shutil
import numpy as np
import cv2
import pandas as pd
from pandarallel import pandarallel
pandarallel.initialize(verbose=0)
from pathlib import Path
from functools import partial
from datetime import datetime
from time import mktime
from skimage import morphology, io
from skimage.measure import label
from configparser import ConfigParser
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError, ResponseStreamingError
from PIL import Image, UnidentifiedImageError, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from io import BytesIO
from time import time

logs_folder = Path(sys.argv[1])
logs_folder.mkdir(exist_ok=True)

bucket_name = "mv1-production"
key = "6658dd0583867ea9940291ef/2024-08-07_1105.jpg"

#doctor, are you sure this work?
#haha, I have no idea!
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

# Create a ConfigParser object
config = ConfigParser()

# Read the .cfg file
config.read('/home/ubuntu/aws_key.cfg')

# Accessing the values
# Access a specific section
settings = config['Secrets']

#DO NOT PRINT secret access key or key id
session = boto3.Session(
    aws_access_key_id=settings['aws_access_key_id'],
    aws_secret_access_key=settings['aws_secret_access_key'],
)
config = BotoConfig(connect_timeout=120, read_timeout=300, retries={"max_attempts": 5, "mode": "standard"})
s3 = session.client('s3', config=config, verify=False)


print("Fetching all keys...")
start_time = time()
jpg_keys = []
continuation_token = None

while True:
    # List objects with an optional prefix (e.g., 'images/')
    if continuation_token:
        response = s3.list_objects_v2(Bucket=bucket_name, ContinuationToken=continuation_token)
    else:
        response = s3.list_objects_v2(Bucket=bucket_name)

    # Filter keys to include only those ending with .jpg
    jpg_keys.extend([obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.jpg')])

    # Check if more results are available (pagination)
    continuation_token = response.get('NextContinuationToken')
    if not continuation_token:
        break
        
print("tokens acquired")

#have empty set if file doesn't exist
processed_keys_set = set()

# read in key file if it exists, otherwise do empty set
processed_keys_file = logs_folder / "processed_keys.txt"
if processed_keys_file.exists():
    with open(processed_keys_file, 'r') as file:
            # Read all lines at once and strip any leading/trailing whitespace
            processed_keys_set = set(line.strip() for line in file if line.strip())
else:
    with open(processed_keys_file, 'w') as file:
        pass

total_key_set = set(jpg_keys)
new_key_set = list(total_key_set - processed_keys_set)
print(f"New images to process: {len(new_key_set)}")
if len(new_key_set) == 0:
    print("No new images to process")
    sys.exit()
print("Key collection & filtering time: ", time() - start_time)

# Add key to processed keys file
def add_key_to_processed_keys_file(key: str):
    with open(processed_keys_file, 'a') as f:
        f.write(f"{key}\n")

def process_and_tag_image(key: str):
    try:
        # Get current tags
        current_tags = s3.get_object_tagging(Bucket=bucket_name, Key=key)
        tag_set = current_tags['TagSet']

        # Check if both tags already exist
        tags_present = {tag['Key']: tag['Value'] for tag in tag_set}
        if 'MayHavePlant' in tags_present and 'PlantPixels' in tags_present:
            print(f"Skipping {key} - already processed")
            add_key_to_processed_keys_file(key)
            return

    except ClientError as error:
        if error.response['Error']['Code'] == 'NoSuchTagSet':
            tag_set = []
        else:
            print(f"Error fetching tags for {key}: {error}")
            return

    try:
        # Get the image object from S3
        s3_object = s3.get_object(Bucket=bucket_name, Key=key)
        
        # Read image into numpy array
        img_data = BytesIO()
        for chunk in s3_object['Body'].iter_chunks(chunk_size=4096):
            img_data.write(chunk)
        img_data.seek(0)
        image = Image.open(img_data)

        # Convert to numpy array
        image_np = np.array(image)

        # Convert to HSV and LAB color spaces
        hsv_image = cv2.cvtColor(image_np, cv2.COLOR_BGR2HSV)
        lab_image = cv2.cvtColor(image_np, cv2.COLOR_BGR2LAB)

        # Define HSV and LAB range for filtering
        hsv_min = np.array([int(28/2), int(20/100*255), int(20/100*255)])
        hsv_max = np.array([int(144/2), 255, 255])
        hsv_mask = cv2.inRange(hsv_image, hsv_min, hsv_max)

        lab_lower = np.array([int(10/100*255), 0, 132])
        lab_upper = np.array([int(90/100*255), 124, 255])
        lab_mask = cv2.inRange(lab_image, lab_lower, lab_upper)

        # Combine the masks and apply to the original image
        combined_mask = cv2.bitwise_and(hsv_mask, lab_mask)

        # Cast binary image to boolean
        bool_mask = combined_mask.astype(bool)

        # Find and fill contours less than 500 in area
        bool_mask = morphology.remove_small_objects(bool_mask, 1000)

        # Cast boolean image to binary
        denoised_mask = np.copy(bool_mask.astype(np.uint8) * 255)

        # Count the number of nonzero pixels
        plant_pixels = cv2.countNonZero(denoised_mask)
        MayHavePlant = int(bool(plant_pixels > 110000))

    except UnidentifiedImageError:
        print(f"{key} won't load")
        return
    except Exception as e:
        print(f"Error processing {key}: {e}")
        return

    # Add or set the tags if they don't exist
    tag_set = set_tag_if_absent(tag_set, 'MayHavePlant', MayHavePlant)
    tag_set = set_tag_if_absent(tag_set, 'PlantPixels', plant_pixels)

    # Apply the updated tag set to the S3 object
    s3.put_object_tagging(
        Bucket=bucket_name,
        Key=key,
        Tagging={
            'TagSet': tag_set
        }
    )

    # Append the processed key to the file
    add_key_to_processed_keys_file(key)
    print(f"Processed {key}")
    

def set_tag_if_absent(tag_set, key_name: str, key_value: int):
    # Check if the tag is already present
    for tag in tag_set:
        if tag['Key'] == key_name:
            return tag_set  # Tag already exists, no need to add
    # Add the tag if it wasn't found
    tag_set.append({'Key': key_name, 'Value': str(key_value)})
    return tag_set

# Example usage:
start_time = time()
print("Processing images...")
# Parallel processing
with ProcessPoolExecutor() as executor:
    executor.map(process_and_tag_image, new_key_set)
print(f"Image processing time: {time() - start_time} seconds")