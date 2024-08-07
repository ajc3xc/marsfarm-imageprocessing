#!/bin/bash

# Function to submit the job and handle dependencies
submit_and_follow() {
    # Submit the job
    local jobid=$(sbatch full_run.sh | cut -d ' ' -f 4)
    echo "Submitted job $jobid"

    # Wait for the job to end
    local job_state=$(sacct --format=State --noheader --jobs $jobid | grep -oP '(COMPLETED|FAILED|TIMEOUT|CANCELLED|NODE_FAIL)')

    # Check if the job timed out
    if [ "$job_state" = "TIMEOUT" ]; then
        echo "Job $jobid timed out, resubmitting..."
        # Resubmit the job with a dependency on itself not to start if the previous job eventually completes successfully
        submit_and_follow
    else
        echo "Job $jobid completed with state $job_state"
    fi
}

# Initial call to the submission function
submit_and_follow