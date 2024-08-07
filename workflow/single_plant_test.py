#!/usr/bin/env python3
import os, sys, shutil
import numpy as np
import cv2
import pandas as pd
from pandarallel import pandarallel
pandarallel.initialize(verbose=0)
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from functools import partial
from datetime import datetime
from time import mktime
from skimage import morphology, io
from skimage.measure import label

from plantcv import plantcv as pcv

outputs_superfolder = Path(sys.argv[1])

bucket_name = "mv1-production"
key = "6658dd0583867ea9940291ef/2024-08-07_1105.jpg"

#doctor, are you sure this work?
#haha, I have no idea!
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create a ConfigParser object
config = configparser.ConfigParser()

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

plant_pixels, MayHavePlant = calculate_area(key)
print(plant_pixels, MayHavePlant)

def calculate_area(key: str):
    # Get the image object from S3
    image_folder = outputs_folder / "images" / Path(key).stem
    image_folder.mkdir(exist_ok=True, parents=True)
    s3_object = s3.get_object(Bucket=bucket_name, Key=key)    
    #read image into numpy array
    #If you can't read it return 0
    try:
        img_data = BytesIO()
        # Download the file in chunks
        for chunk in s3_object['Body'].iter_chunks(chunk_size=4096):
            img_data.write(chunk)

        # Ensure the beginning of the file is at the start
        img_data.seek(0)
        image = Image.open(img_data)
    #So many ways to fail, so little time
    except UnidentifiedImageError as e:
        print(f"{key} won't load")
        return 0
    except urllib3.exceptions.SSLError:
        print(f"SSL failed for {key}")
        return 0
    except ResponseStreamingError as e:
        print(f"ResponseStreamingError for {key}")
        return 0
    image_np = np.array(image)
    #load in image
    #using skimage for file import since cv2 wasn't working
    image_np = io.imread(str(filename))

    # Convert to HSV and LAB color spaces
    #HSV - Hue, Seperation, Value
    #LAB - Lightness, red-green, blue-yellow
    hsv_image = cv2.cvtColor(image_np, cv2.COLOR_BGR2HSV)
    lab_image = cv2.cvtColor(image_np, cv2.COLOR_BGR2LAB)

    # Define HSV range for filtering using OpenCV
    # OpenCV uses 0-180 for Hue, so the values are halved
    hsv_min = np.array([int(28/2), int(20/100*255), int(20/100*255)])
    hsv_max = np.array([int(144/2), 255, 255])
    hsv_mask = cv2.inRange(hsv_image, hsv_min, hsv_max)

    # Define LAB range for filtering using OpenCV
    # OpenCV uses 0-255 for L, a*, and b*
    # Note: 'a' and 'b' ranges need to be shifted from [-128, 127] to [0, 255]
    # L is scaled from [0, 100] in LAB to [0, 255] in OpenCV
    lab_lower = np.array([int(10/100*255), 0, 132])
    lab_upper = np.array([int(90/100*255), 124, 255])
    lab_mask = cv2.inRange(lab_image, lab_lower, lab_upper)

    # Combine the masks (logical AND) and apply to the original image
    combined_mask = cv2.bitwise_and(hsv_mask, lab_mask)

    # Cast binary image to boolean
    bool_mask = combined_mask.astype(bool)

    # Find and fill contours less than 500 in area
    bool_mask = morphology.remove_small_objects(bool_mask, 1000)

    # Cast boolean image to binary and make a copy of the binary image for returning
    denoised_mask = np.copy(bool_mask.astype(np.uint8) * 255)

    #count the number of nonzero pixels, determine if > 110k
    plant_pixels = cv2.countNonZero(denoised_mask)
    MayHavePlant = bool(plant_pixels > 110000)

    #create labels for masks that may have plants, count number of objects
    number_of_plants = 0
    #if MayHavePlant:
        #labeled_mask = label(denoised_mask, connectivity=1)  # You can adjust connectivity (1 or 2)

        # Find the number of objects by ignoring the background (label 0)
       # number_of_plants = len(np.unique(labeled_mask)) - 1  # Subtract one for the background label

    #export masked and denoised image to file
    #cv2 only works with strings, not filepaths
    masked_image_path = str(mask_folder / f"{filename.stem}_mask_plantpixels_{plant_pixels}_mayhaveplant_{MayHavePlant}_nplants_{number_of_plants}.jpg")
    cv2.imwrite(masked_image_path, denoised_mask)


    # Here, you might want to save or further process the result_image
    # For demonstration, let's just return the number of white pixels in the mask
    return plant_pixels, MayHavePlant





    