#!/bin/bash
#SBATCH --job-name=plant_analysis
#SBATCH --time=2-00:00:00            # Adjust time limit as needed
##SBATCH --output=temp.out
#SBATCH --error=temp.err

# Activate Anaconda and environment
eval "$(conda shell.bash hook)"  # Modify path according to your Anaconda install
conda activate plantenv_pcv4_jupyter

# Environment variables
bucket_name="mv1-production"

# Execute the script
python -u full_run.py $bucket_name 2>&1 | tee /mnt/stor/ceph/csb/marsfarm/projects/plant_detection_full_run/logs/output.log