#!/bin/bash

#make sure you are in the same directory as this file when running it
full_bucket_workflow()
{(
    set -Eeo pipefail
    # ACTIVATE ANACONDA
    eval "$(conda shell.bash hook)"
    conda activate imageprocessing_minimal

    #script test inputs
    local outputs_superfolder="/home/ubuntu/marsfarm-imageprocessing/outputs"

    #shows you what node jupyter lab is running on
    python3 full_bucket_workflow.py $outputs_superfolder
)}

export -f full_bucket_workflow

full_bucket_workflow
