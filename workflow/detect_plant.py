#!/usr/bin/env python3
import os, sys, shutil
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError, ResponseStreamingError
import numpy as np
import cv2
import pandas as pd
import csv
from pandarallel import pandarallel
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import configparser
pandarallel.initialize(verbose=0)
from PIL import Image, UnidentifiedImageError, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from io import BytesIO
import matplotlib.pyplot as plt
from pathlib import Path
from functools import partial
from datetime import datetime
from time import mktime

from plantcv import plantcv as pcv

#doctor, are you sure this work?
#haha, I have no idea!
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create a ConfigParser object
config = configparser.ConfigParser()

# Read the .cfg file
config.read('/mnt/stor/ceph/csb/marsfarm/projects/aws_key/aws_key.cfg')

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

bucket_name = sys.argv[1]
folder_name = sys.argv[2]
outputs_superfolder = Path(sys.argv[3])

print(f"beginning run for bucket {bucket_name}, folder {folder_name}")

#outputs_superfolder = Path("/mnt/stor/ceph/csb/marsfarm/projects/NN_plant_detection/outputs")
outputs_folder = outputs_superfolder / Path(bucket_name) / folder_name
outputs_folder.mkdir(exist_ok=True, parents=True)

class area_plotter:
    #login to s3 using credentials
    def __init__(self,
                 folder_name: str = folder_name,
                 bucket_name: str = bucket_name,
                 outputs_folder: str = outputs_folder):

        self.outputs_folder = outputs_folder
        
        # Pagination configuration
        self.folder_name = folder_name
        self.bucket_name = bucket_name
        paginator = s3.get_paginator('list_objects_v2')
        self.page_iterator = paginator.paginate(Bucket=self.bucket_name, Prefix=self.folder_name)
        
        #path to files containing key paths
        self.keyfile = self.outputs_folder / "keys.txt"

        #check if the tag of the first plant has 'mayhaveplant'
        #newer images have newer dates, so they'll be ordered last
        already_tagged = False
        if self.check_if_plant_in_folder():
            already_tagged = True
        
        #skip this folder if it already has been fully processed
        area_file = self.outputs_folder / "areas.csv"
        plot_path = self.outputs_folder / "area_plot.png"
        if not plot_path.is_file():
            #generate key file if it doesn't exist
            #for the sake of convenience, I'm only generating the key file once
            #I just want to see a rough plot of what the plant area looks like, even if more images are added to the bucket.
            if not self.keyfile.is_file():
                self.get_keys_and_save()
            
            #read in key file as pandas series, sort values in place from least to greatest
            self.keys: pd.DataFrame = pd.read_csv(self.keyfile, header=None, index_col=False, names=['keys'])
            
            self.keys.sort_values(inplace=True, by='keys')
            self.keys: pd.Series = self.keys['keys']

            #create pandas series of hours from start
            hours_from_start: pd.Series = self.get_hours_from_start()
            
            #calculate area, save area and hours from start to csv file for caching
            #this is by far the longest part of the process
            if not area_file.is_file():
                base_filenames = self.keys.parallel_apply(lambda filename: Path(filename).stem)
                self.areas_df = pd.DataFrame({"Date": base_filenames, "Hours From Start": hours_from_start})
                areas_results = self.keys.parallel_apply(area_plotter.calculate_area)
                self.areas_df['Area'], self.areas_df["MayHavePlant"], self.areas_df["EstimatedPlantCount"] = zip(*areas_results)
            else:
                self.areas_df = pd.read_csv(area_file)
            
            #self.areas_df["MayHavePlant"].astype(bool)
            #concatenate both date, hours and area and export to csv
            #self.areas_df = pd.DataFrame({"Date": base_filenames, "Hours From Start": hours_from_start, "Area": areas})

            # Label contiguous blocks
            blocks = self.areas_df['MayHavePlant'].diff().ne(0).cumsum()

            # Count the False gaps
            gap_counts = (~self.areas_df['MayHavePlant']).groupby(blocks).sum()

            # Filter blocks where True exists
            true_blocks = self.areas_df['MayHavePlant'].groupby(blocks).any()

            # Identify blocks to be labeled with group numbers
            group_labels = pd.Series(0, index=self.areas_df.index)
            current_group = 0
            previous_block_index = -1

            for block_index, is_true in true_blocks.items():
                if is_true:
                    # Determine if this block should start a new group
                    if previous_block_index == -1 or gap_counts[previous_block_index] >= 6:
                        current_group += 1
                    group_labels[blocks == block_index] = current_group
                previous_block_index = block_index

            crop_groups = group_labels.max()
            #print(crop_groups)
            self.areas_df['Group'] = group_labels

            self.areas_df.to_csv(area_file, index=False)
            
            if not already_tagged:
                #check if there are any plants
                mayhaveplant = self.areas_df["MayHavePlant"].any()
                
                #If any potential plants are found in the bucket, add tag to bucket and folder
                
                #First, add or set tag in bucket
                try:
                    current_tags = s3.get_bucket_tagging(Bucket=bucket_name)
                    tag_set = current_tags['TagSet']              
                except ClientError as error:
                    if error.response['Error']['Code'] == 'NoSuchTagSet': tag_set = []
                    else: raise
                
                # We'll use a dictionary to track whether each tag has been found and updated
                found_tags = {'MayHavePlant': False, 'CropGroups': False}

                # Iterate over the tag set to find the necessary tags and update them
                for tag in tag_set:
                    if tag['Key'] == 'MayHavePlant':
                        if tag['Value'] == mayhaveplant:
                            bucket_tag_set_right = True
                        tag['Value'] = str(mayhaveplant)  # Update the tag value
                        found_tags['MayHavePlant'] = True  # Mark as found and updated
                    elif tag['Key'] == 'CropGroups':
                        if tag['Value'] == crop_groups:
                            bucket_tag_set_right = True
                        tag['Value'] = str(crop_groups)  # Update the tag value
                        found_tags['CropGroups'] = True  # Mark as found and updated

                # Check if any tags were not found in the existing tag set and need to be added
                if not found_tags['MayHavePlant']:
                    tag_set.append({'Key': 'MayHavePlant', 'Value': str(mayhaveplant)})  # Add the tag if not found
                if not found_tags['CropGroups']:
                    tag_set.append({'Key': 'CropGroups', 'Value': str(crop_groups)})  # Add the tag if not found

                # Apply the updated tag set to the bucket
                if all(found_tags.values()):
                    s3.put_bucket_tagging(
                        Bucket=bucket_name,
                        Tagging={
                            'TagSet': tag_set
                        }
                    )
                    
                #now that the bucket tag is set, set the individual folders
                #It would be more lightweight to use multithreading, but I don't care that much
                set_tag_function = partial(area_plotter.set_tag_mayhaveplant, mayhaveplant)
                self.keys.parallel_apply(set_tag_function)                       
        
            #plot the plant area over time, save as png       
            plt.clf()
            subplots = 4
            fig, axes = plt.subplots(1, subplots, figsize=(subplots * 5,8))
            
            #plot plant area over time
            i=0

            #plot filtered area over time
            axes[i].plot(self.areas_df['Hours From Start'], self.areas_df['Area'], color='red')
            axes[i].set_title("Plant Area Over Time")
            axes[i].set_xlabel("Time (hours)")
            axes[i].set_ylabel("Plant area (pixels)")
            i += 1
            
            #plot plant group over time
            axes[i].plot(self.areas_df['Hours From Start'], self.areas_df['Group'], color='green')
            axes[i].set_title("Plant Crop Group Over Time")
            axes[i].set_xlabel("Time (hours)")
            axes[i].set_ylabel("Plant Detected")
            i += 1

            #plot plant group over time
            axes[i].plot(self.areas_df['Hours From Start'], self.areas_df['EstimatedPlantCount'], color='black')
            axes[i].set_title("Estimated Plant Count Over Time")
            axes[i].set_xlabel("Time (hours)")
            axes[i].set_ylabel("Plant Detected")
            i += 1
            
            #plot hasplant over time
            axes[i].plot(self.areas_df['Hours From Start'], self.areas_df['MayHavePlant'])
            axes[i].set_title("Plant Detected Over Time")
            axes[i].set_xlabel("Time (hours)")
            axes[i].set_ylabel("Plant Detected")
            fig.suptitle("Analysis of methods for determining if plant is being grown")
            fig.tight_layout()

            #plot plant group over time
            
            plt.savefig(plot_path)
            print("Finished Processing")
        else:
            print("Already processed")
            return

    #check if plants are in the folder   
    def check_if_plant_in_folder(self):
        # Check if there are any contents returned
        for page in self.page_iterator:
            if 'Contents' in page and page['Contents']:
                first_object_key = page['Contents'][0]['Key']
                break
            else:
                print("No objects found in the folder")
                sys.exit()

        # Get the tags for the first object
        tagging_info = s3.get_object_tagging(Bucket=self.bucket_name, Key=first_object_key)

        # Check the tags for 'mayhaveplant'
        tag_dict = {tag['Key']: tag['Value'] for tag in tagging_info['TagSet']}
        if 'CropGroups' in tag_dict:
            if tag_dict['CropGroups'] == '0':
                print(f"folder {self.folder_name} in bucket {self.bucket_name} has no plant images")
                sys.exit()
            else:
                print("folder has plants in it")
                return 1
        else:
            print("Folder hasn't been ran yet")
            return 0

    
    @staticmethod
    def set_tag_mayhaveplant(mayhaveplant: bool, key: str):
        #First, add or set tag in bucket
        try:
            current_tags = s3.get_object_tagging(Bucket=bucket_name, Key=key)
            tag_set = current_tags['TagSet']              
        except ClientError as error:
            if error.response['Error']['Code'] == 'NoSuchTagSet': tag_set = []
            else: raise
        
        # Iterate over the tag set to find the 'mayhaveplant' tag
        for tag in tag_set:
            if tag['Key'] == 'MayHavePlant':
                tag['Value'] = str(mayhaveplant)
                break
        else:
            # If no break was encountered, it means the tag was not found
            tag_set.append({'Key': 'MayHavePlant', 'Value': str(mayhaveplant)})  # Add the tag

        # Apply the updated tag set to the bucket
        s3.put_object_tagging(
            Bucket=bucket_name,
            Key=key,
            Tagging={
                'TagSet': tag_set
            }
        )
    
    @staticmethod
    def calculate_area(key: str):
        # Get the image object from S3
        image_folder = outputs_folder / "images" / Path(key).stem
        image_folder.mkdir(exist_ok=True, parents=True)
        base_filename = image_folder / ("base_" + str(Path(key).name))
        if not base_filename.is_file(): s3.download_file(bucket_name, key, base_filename)
        image_np = cv2.imread(str(base_filename))
        '''s3_object = s3.get_object(Bucket=bucket_name, Key=key)
        #img_data = s3_object['Body'].read()
        
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

        #output base image to file
        cv2.imwrite(str(outputs_folder / "base_image" / key), image_np)'''

        # Convert to HSV and LAB color spaces
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

        #output mask to file
        #mask_filename = image_folder / ("mask_" + Path(key).name)
        #if not mask_filename.is_file(): cv2.imwrite(str(mask_filename), combined_mask)

        '''# Apply morphological opening to remove small objects
        kernel = np.ones((3,3), np.uint8)
        opening = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel, iterations=2)

        # Remove small regions based on area
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(opening, connectivity=8)
        min_area = 500  # minimum area threshold, needs tuning
        large_components = np.zeros_like(combined_mask)
        
        for i in range(1, num_labels):  # skipping the background label
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                large_components[labels == i] = 255'''

        #remove small holes in the image so object detection won't be as bad
        denoised_mask = pcv.fill(bin_img=combined_mask, size=300)

        #output mask to file
        #denoised_filename = image_folder / ("denoised_mask_" + Path(key).name)
        #if not denoised_filename.is_file(): cv2.imwrite(str(denoised_filename), denoised_mask)

        #count the number of nonzero pixels, determine if > 110k
        plant_pixels = cv2.countNonZero(denoised_mask)
        MayHavePlant = bool(plant_pixels > 110000)

        #create labels for masks that may have plants, count number of objects
        number_of_plants = 0
        if MayHavePlant:
            _, number_of_plants = pcv.create_labels(mask=denoised_mask)

        # Here, you might want to save or further process the result_image
        # For demonstration, let's just return the number of white pixels in the mask
        return plant_pixels, MayHavePlant, number_of_plants
        
    
    #get keys from single page of s3 bucket
    @staticmethod
    def retrieve_keys(page):
        # Filter and return only keys that end with '.jpg'
        keys = [content['Key'] for content in page['Contents'] if content['Key'].endswith('.jpg')] if 'Contents' in page else []
        return keys

    
    # Function to get all keys and save to a file
    def get_keys_and_save(self):
        # Use ThreadPoolExecutor to process the pages in parallel
        num_threads = 2 * os.cpu_count() or 1
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Map the retrieve_keys function to each page
            results = executor.map(self.retrieve_keys, self.page_iterator)

        # Flatten the list of lists into a single list of keys
        all_keys = [key for sublist in results for key in sublist]

        #check if any keys were found
        if not all_keys:
            print(f"No keys found in folder {self.folder_name}")
            sys.exit(0)

        # Save the keys to the specified file
        with open(self.keyfile, 'w', newline='') as file:
            writer = csv.writer(file)
            for key in all_keys:
                writer.writerow([key])
                 
    def get_hours_from_start(self) -> pd.Series(int):
        #subfunction to convert filename to unix time
        #get base filename (should be named after time), then convert to unix time
        def convert_to_unixtime(filename: str):
            base_filename = Path(filename).stem 
            dt = datetime.strptime(str(base_filename), "%Y-%m-%d_%H%M")
            return int(mktime(dt.timetuple()))
        
        #get the stem of the file (no path, no file extension)
        unix_times = self.keys.apply(convert_to_unixtime)
        
        #calculate unix times from the start
        start_time = unix_times.iloc[0]
        unix_hours_from_start = unix_times.apply(lambda time: (time - start_time) // 3600)       
        return unix_hours_from_start

#generate s3 bucket, keys and areas
area_plotter = area_plotter()

print(f"finished run for bucket {bucket_name}, folder {folder_name}")