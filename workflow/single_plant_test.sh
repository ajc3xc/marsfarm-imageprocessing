#!/bin/bash

#make sure you are in the same directory as this file when running it
detect_plant()
{(
    set -Eeo pipefail
    # ACTIVATE ANACONDA
    eval "$(conda shell.bash hook)"
    conda activate imageprocessing_minimal

    #script test inputs
    local outputs_superfolder="~/marsfarm-imageprocessing/outputs"

    #shows you what node jupyter lab is running on
    python3 single_plant_test.py $outputs_superfolder
)}

export -f detect_plant

detect_plant
