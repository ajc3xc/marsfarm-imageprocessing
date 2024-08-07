#!/usr/bin/env python3

from pathlib import Path
import boto3
import configparser
import sys
from subprocess import Popen, PIPE, run
from time import time, sleep
from concurrent.futures import ThreadPoolExecutor

import os
#I hate ssl
#os.environ['PYTHONHTTPSVERIFY'] = '0'

# Unset conflicting SLURM memory environment variables
#os.environ.pop('SLURM_MEM_PER_CPU', None)
#os.environ.pop('SLURM_MEM_PER_GPU', None)
#os.environ.pop('SLURM_MEM_PER_NODE', None)

bucket_name = sys.argv[1]
outputs_superfolder = "/mnt/stor/ceph/csb/marsfarm/projects/plant_detection_full_run/outputs"
log_path = "/mnt/stor/ceph/csb/marsfarm/projects/plant_detection_full_run/logs"

# Setup boto3 client
def load_client():
    config = configparser.ConfigParser()
    config.read('/mnt/stor/ceph/csb/marsfarm/projects/aws_key/aws_key.cfg')
    settings = config['Secrets']

    #DO NOT PRINT secret access key or key id
    session = boto3.Session(
        aws_access_key_id=settings['aws_access_key_id'],
        aws_secret_access_key=settings['aws_secret_access_key'],
    )
    
    global s3
    s3 = session.client('s3')
    
load_client()


response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
print(".")

def list_top_level_folders(bucket_name):
    response = s3.list_objects_v2(Bucket=bucket_name, Delimiter='/')
    if 'CommonPrefixes' in response:
        folders = [prefix['Prefix'] for prefix in response['CommonPrefixes']]
        return folders
    else:
        return []

#runs one folder on one node 
def plot_green_custom(bucket_folder: str, number_of_cores: int):
    cli_arguments = [bucket_name, bucket_folder, outputs_superfolder]
    run_command = [
        "srun",
        "--exclusive",
        "--preserve-env",
        "--job-name=plot_green",
        "--nodes=1",
        "--ntasks=1",
        "--partition=requeue",
        '--time=2-00:00:00',
        "python3",
        "detect_plant.py"
    ] + cli_arguments
    
    return Popen(run_command)

def plot_green(bucket_folder):
    cli_arguments = [bucket_name, bucket_folder, outputs_superfolder]
    #f"-o {log_path}/{bucket_folder}.log",
    run_command = [
        "srun",
        "--exclusive",
        "--job-name=detect_plant",
        "--nodes=1",
        "--export=ALL",
        "--ntasks=1",
        "--ntasks-per-node=1",
        "--partition=requeue",
        '--time=2-00:00:00',
        "detect_plant.py"  
    ] + cli_arguments
    
    # Start the process without redirecting stdout and stderr
    result = run(run_command)
    if result.returncode != 0:
        print(f"Error occurred in folder {bucket_folder} with error code {result.returncode}")
        sys.exit(1)

def execute_jobs(folders, batch_number):
    print(f"running batch {batch_number}")
    with ThreadPoolExecutor() as executor:
        executor.map(plot_green, folders)
    print("All jobs completed successfully.")

    


#get number of nodes to run simultaneously from config
config = configparser.ConfigParser()
config.read("multirun_config.cfg")
max_nodes = int(config.get("NODES", "NODES"))

# Run jobs in batches of up to max_nodes
start_time = time()
def get_idle_nodes():
    command = 'sinfo --state=idle --noheader -o "%A"'

    result = run(
        command,
        shell=True,  # Allow shell operators such as pipes
        text=True,  # Capture output as text
        capture_output=True,  # Capture stdout and stderr
        check=True  # Raise an error if the command fails
    )
    # Convert the output from string to integer
    idle_nodes = int(result.stdout.strip().split('/')[1] or 0)
    return idle_nodes

#function to calculate how many cores are left to run
def calculate_remaining_cores(max_nodes):
    
    remaining_cores = 64 * max_nodes
    
    # calculate how many cores are left
    command = 'sinfo -o "%N %t %C" | awk \'$2=="idle"{split($3, cpus, "/"); idle += cpus[2]} END {print idle}\''
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, text=True)

    # Capture the output, ensuring we handle the case where no idle cores are reported
    idle_cores = int(result.stdout.strip() or 0)

    #readjust if there isn't enough idle cores left
    remaining_cores = min(remaining_cores, idle_cores)

    return remaining_cores

#get bucket folders
bucket_folders = list_top_level_folders(bucket_name)

#print(len(bucket_folders))
#sys.exit(1)

i = 0
batch_num = 0
sleep_time = 30
print("Starting run")
while i < len(bucket_folders):
    print(f"{len(bucket_folders) - i} folders left to run")
    jobs = []
    idle_nodes = get_idle_nodes()
    nodes_to_run = min(max_nodes, idle_nodes)
    print(f"{idle_nodes} idle nodes found. Running on {nodes_to_run} nodes")
    if nodes_to_run > 0:  # Ensure there are nodes to run jobs
        batch_folders = bucket_folders[i:i + nodes_to_run]
        jobs = execute_jobs(batch_folders, batch_num)
        batch_num += 1
        i += nodes_to_run  # Move the index forward by the number of nodes used
    remaining_nodes = max_nodes - nodes_to_run
    if remaining_nodes > 0:
        print(f"No idle nodes available, checking again in {sleep_time} seconds")
        sleep(sleep_time)  # Wait for some time before checking again, e.g., 60 seconds
        continue
    #print(i)

    '''remaining_cores = calculate_remaining_cores(remaining_nodes)
    if not remaining_cores:
        print("No idle nodes available, waiting...")
        sleep(60)  # Wait for some time before checking again, e.g., 60 seconds
        continue

    # Define the command to run
    command = "sinfo -o \"%N %t %C\" --noheader | awk '$2==\"idle\" && ($3 ~ /\\/[1-9][0-9]*\\//) { split($3, cpus, \"/\"); if (cpus[2] > 0) print $1, cpus[2] }'"

    # Execute the command
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, text=True)

    # Initialize a list to store node data
    node_idle_cores = []

    # Process each line of the output
    run_jobs = []
    for line in result.stdout.strip().split("\n"):
        if line:  # Ensure the line is not empty
            node_name, idle_cores = line.split()
            idle_cores = int(idle_cores)  # Convert idle_cores to integer
            if idle_cores > 0 and remaining_cores > 0:
                run_jobs.append((node_name, idle_cores))
                remaining_cores -= idle_cores

    #run the jobs
    execute_jobs(run_jobs)



    while True:
        #calculate remaining_cores
        remaining_cores = calculate_remaining_cores(remaining_nodes)
        if not remaining_cores:
            print("No idle nodes available, waiting...")
            sleep(60)  # Wait for some time before checking again, e.g., 60 seconds
            break

        #iterate through all the general nodes
        # Process each line of the output
        for line in result.stdout.strip().split("\n"):
            node_name, status, cpus = line.split()
            allocated, idle, other, total = cpus.split('/')
            idle = int(idle)  # Convert the number of idle cores to an integer

            # Check if the number of idle cores is greater than zero
            if idle > 0:
                node_idle_cores.append((node_name, idle))
                print(f"Node {node_name} has {idle} idle cores.")'''

print(f"Runtime (minutes): {(time() - start_time) / 60}")
