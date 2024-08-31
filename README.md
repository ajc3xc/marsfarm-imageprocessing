# marsfarm-imageprocessing
Repository for automating processing of images on ec2 cluster.<br/>
Calculates plant pixels and if plants are detected in the image, sets them in the image's tags<br/>
This program is designed to work on MarsFarm's mv1-production bucket<br/>

## How the workflow works:
- Load in anaconda environment in [__run.sh__](workflow/full_bucket_workflow.sh)
- [__Connect to boto3 client__](workflow/full_bucket_workflow.py#L45-L51)
- [__Load in all keys__](workflow/full_bucket_workflow.py#L59-L72) from mv1 production bucket
- [__Load in keys from processed keys file, filter out any keys already in processed keys file__](workflow/full_bucket_workflow.py#L76-L95)
- [Process and tag the images in parallel](workflow/full_bucket_workflow.py#L199-L205). For each image:
  - [Load in current tags](workflow/full_bucket_workflow.py#L103-L120). If plantpixel and mayhaveplant tags exist, skip on image
  - [Load in image from s3, apply filters and calculate plantpixels and mayhaveplant](workflow/full_bucket_workflow.py#L122-L170)
  - [Sets tags of image](workflow/full_bucket_workflow.py#L172-L183), [add key to processed key file](workflow/full_bucket_workflow.py#L186)

## [Single Plant Workflow](workflow/single_plant_test.py#L122-L170)
A simple workflow to test out this workflow for just a single image in the mv1 production bucket. 
