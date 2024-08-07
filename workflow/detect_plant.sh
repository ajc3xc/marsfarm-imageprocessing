#!/bin/bash

#make sure you are in the same directory as this file when running it
detect_plant()
{(
    set -Eeo pipefail
    # ACTIVATE ANACONDA
    eval "$(conda shell.bash hook)"
    conda activate plantenv_pcv4_jupyter

    #script test inputs
    local bucket_name="mv1-production"
    local folder_name="63fe89ab8ff20577fe003e76"
    local outputs_superfolder="/mnt/stor/ceph/csb/marsfarm/projects/plant_analysis_full_run/outputs"

    #shows you what node jupyter lab is running on
    python3 detect_plant.py $bucket_name $folder_name $outputs_superfolder
)}

export -f detect_plant

#encapsulate the rest of the code within the bash function
srun --time=2-00:00:00 --export=ALL --exclusive --job-name=plot_green bash -c 'detect_plant'
