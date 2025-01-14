#
# manage_api_submission.py
#
# Semi-automated process for submitting and managing camera trap
# API jobs.
#

#%% Imports

import os
import ntpath
import posixpath

from urllib.parse import urlsplit, unquote
import path_utils

from api.batch_processing.data_preparation import prepare_api_submission
from api.batch_processing.postprocessing import combine_api_outputs

from api.batch_processing.postprocessing.postprocess_batch_results import PostProcessingOptions
from api.batch_processing.postprocessing.postprocess_batch_results import process_batch_results


#%% Constants I set per job

account_name = 'blah'
container_name = 'blah'
job_set_name = 'institution-20191215'
container_prefix = ''
base_output_folder_name = r'f:\institution\20191215'
folder_names = ['folder1','folder2','folder3']

# These point to the same container; the read-only token is used for
# accessing images; the write-enabled token is used for writing file lists
read_only_sas_token = '?st=2019-12...'
write_sas_token = '?st=2019-12...'
image_base = 'x:\\'

caller = 'caller'
task_status_endpoint_url = 'http://blah.endpoint.com:6022/v2/camera-trap/detection-batch/task'
submission_endpoint_url = 'http://blah.endpoint.com:6022/v2/camera-trap/detection-batch/request_detections'


#%% Derived variables, path setup

container_base_url = 'https://' + account_name + '.blob.core.windows.net/' + container_name
read_only_sas_url = container_base_url + read_only_sas_token
write_sas_url = container_base_url + write_sas_token

filename_base = os.path.join(base_output_folder_name,job_set_name)
os.makedirs(filename_base,exist_ok=True)

raw_api_output_folder = os.path.join(filename_base,'raw_api_outputs')
os.makedirs(raw_api_output_folder,exist_ok=True)

combined_api_output_folder = os.path.join(filename_base,'combined_api_outputs')
os.makedirs(combined_api_output_folder,exist_ok=True)

postprocessing_output_folder = os.path.join(filename_base,'postprocessing')
os.makedirs(postprocessing_output_folder,exist_ok=True)

# Turn warnings into errors if more than this many images are missing
max_tolerable_missing_images = 20

# import clipboard; clipboard.copy(read_only_sas_url)
# configure mount point with rclone config
# rclone mount mountname: z:

# Not yet automated:
#
# Mounting the image source (see comment above)
#
# Submitting the jobs (code written below, but it doesn't really work)
#
# Handling failed jobs/shards/images (though most of the code exists in generate_resubmission_list)
#
# Pushing the final results to shared storage and generating a SAS URL to share with the collaborator
#
# Pushing the previews to shared storage


#%% URL parsing

# https://gist.github.com/zed/c2168b9c52b032b5fb7d
def url_to_filename(url):
    
    # scheme, netloc, path, query, fragment
    urlpath = urlsplit(url).path
    
    basename = posixpath.basename(unquote(urlpath))
    if (os.path.basename(basename) != basename or
        unquote(posixpath.basename(urlpath)) != basename):
        raise ValueError  # reject '%2f' or 'dir%5Cbasename.ext' on Windows
        
    return basename


#%% Enumerate blobs to files

list_files = []

# folder_name = folder_names[0]
for folder_name in folder_names:
    list_file = os.path.join(filename_base,folder_name + '_all.json')
    prefix = container_prefix + folder_name
    file_list = prepare_api_submission.enumerate_blobs_to_file(output_file=list_file,
                                    account_name=account_name,sas_token=read_only_sas_token,
                                    container_name=container_name,
                                    account_key=None,
                                    rmatch=None,prefix=prefix)
    list_files.append(list_file)

assert len(list_files) == len(folder_names)


#%% Divide images into chunks for each folder

# This will be a list of lists
folder_chunks = []

# list_file = list_files[0]
for list_file in list_files:
    
    chunked_files,chunks = prepare_api_submission.divide_files_into_tasks(list_file)
    print('Divided images into files:')
    for i_fn,fn in enumerate(chunked_files):
        new_fn = chunked_files[i_fn].replace('_all','')
        os.rename(fn, new_fn)
        chunked_files[i_fn] = new_fn
        print(fn,len(chunks[i_fn]))
    folder_chunks.append(chunked_files)

assert len(folder_chunks) == len(folder_names)


#%% Copy image lists to blob storage for each job

# Maps  job name to a remote path
job_name_to_list_url = {}
job_names_by_task_group = []

# chunked_folder_files = folder_chunks[0]; chunk_file = chunked_folder_files[0]
for chunked_folder_files in folder_chunks:
    
    job_names_this_task_group = []
    
    for chunk_file in chunked_folder_files:
        
        job_name = job_set_name + '_' + os.path.splitext(ntpath.basename(chunk_file))[0]
        
        # periods not allowed in job names
        job_name = job_name.replace('.','_')
        
        remote_path = 'api_inputs/' + job_set_name + '/' + ntpath.basename(chunk_file)
        print('Job {}: uploading {} to {}'.format(
            job_name,chunk_file,remote_path))
        prepare_api_submission.copy_file_to_blob(account_name,write_sas_token,
                                                     container_name,chunk_file,
                                                     remote_path)
        assert job_name not in job_name_to_list_url
        list_url = read_only_sas_url.replace('?','/' + remote_path + '?')
        job_name_to_list_url[job_name] = list_url
        job_names_this_task_group.append(job_name)    
        
    job_names_by_task_group.append(job_names_this_task_group)

    # ...for each task within this task group

# ...for each folder


#%% Generate API calls for each job

import itertools
from api.batch_processing.data_preparation import prepare_api_submission

request_strings_by_task_group = []

# job_name = list(job_name_to_list_url.keys())[0]
for task_group_job_names in job_names_by_task_group:
    
    request_strings_this_task_group = []
    
    for job_name in task_group_job_names:
        list_url = job_name_to_list_url[job_name]
        s,d = prepare_api_submission.generate_api_query(read_only_sas_url,
                                                  list_url,
                                                  job_name,
                                                  caller,
                                                  image_path_prefix=None)
        request_strings_this_task_group.append(s)
        
    request_strings_by_task_group.append(request_strings_this_task_group)

request_strings = list(itertools.chain.from_iterable(request_strings_by_task_group))

for s in request_strings:
    print(s)

import clipboard
clipboard.copy('\n\n'.join(request_strings))


#%% Estimate total time

import json
import humanfriendly
n_images = 0
for fn in list_files:
    images = json.load(open(fn))
    n_images += len(images)
    
print('Processing a total of {} images'.format(n_images))

expected_seconds = (0.8 / 16) * n_images
print('Expected time: {}'.format(humanfriendly.format_timespan(expected_seconds)))


#%% Run the jobs (still in progress, doesn't actually work yet)

# Not working yet, something is wrong with my post call

# import requests

task_ids_by_task_group = []

# task_group_request_strings = request_strings_by_task_group[0]; request_string = task_group_request_strings[0]
for task_group_request_strings in request_strings_by_task_group:
    
    task_ids_this_task_group = []
    for request_string in task_group_request_strings:
                
        request_string = request_string.replace('\n','')
        # response = requests.post(submission_endpoint_url,json=request_string)
        # print(response.json())
        task_id = 0
        task_ids_this_task_group.append(task_id)
    
    task_ids_by_task_group.append(task_ids_this_task_group)
    
        
# List of task IDs, grouped by logical job
task_groups = task_ids_by_task_group


#%% Manually define task groups if we ran the jobs manually

task_groups = [[7618], [7452], [9090]]


#%% Status check

for task_group in task_groups:
    for task_id in task_group:
        response,status = prepare_api_submission.fetch_task_status(task_status_endpoint_url,task_id)
        assert status == 200
        print(response)


#%% Look for failed shards or missing images, start new jobs if necessary

n_resubmissions = 0

# i_task_group = 0; task_group = task_groups[i_task_group]; task_id = task_group[0]
for i_task_group,task_group in enumerate(task_groups):
    
    for task_id in task_group:
        
        response,status = prepare_api_submission.fetch_task_status(task_status_endpoint_url,task_id)
        assert status == 200
        n_failed_shards = int(response['status']['message']['num_failed_shards'])
        
        # assert n_failed_shards == 0
        
        if n_failed_shards != 0:
            print('Warning: {} failed shards for task {}'.format(n_failed_shards,task_id))
        
        output_file_urls = prepare_api_submission.get_output_file_urls(response)
        detections_url = output_file_urls['detections']
        fn = url_to_filename(detections_url)
        
        # Each task group corresponds to one of our folders
        assert (folder_names[i_task_group] in fn) or \
            (prepare_api_submission.clean_request_name(folder_names[i_task_group]) in fn)
        assert 'chunk' in fn
        
        missing_images_fn = fn.replace('.json','_missing.json')
        missing_images_fn = os.path.join(raw_api_output_folder, missing_images_fn)
        
        missing_images,non_images = \
            prepare_api_submission.generate_resubmission_list(
                task_status_endpoint_url,task_id,missing_images_fn)

        if len(missing_images) < max_tolerable_missing_images:
            continue

        print('Warning: {} missing images for task {}'.format(len(missing_images),task_id))
        
        job_name = folder_names[i_task_group] + '_' + str(task_id) + '_missing_images'
        remote_path = 'api_inputs/' + job_set_name + '/' + job_name + '.json'
        print('Job {}: uploading {} to {}'.format(
            job_name,missing_images_fn,remote_path))
        prepare_api_submission.copy_file_to_blob(account_name,write_sas_token,
                                                     container_name,missing_images_fn,
                                                     remote_path)
        list_url = read_only_sas_url.replace('?','/' + remote_path + '?')                
        s,d = prepare_api_submission.generate_api_query(read_only_sas_url,
                                          list_url,
                                          job_name,
                                          caller,
                                          image_path_prefix=None)
        
        print('\nResbumission job for {}:\n'.format(task_id))
        print(s)
        n_resubmissions += 1
        
    # ...for each task
        
# ...for each task group

if n_resubmissions == 0:
    print('No resubmissions necessary')
    

#%% Resubmit jobs for failed shards, add to appropriate task groups

if False:
    
    #%%
    
    resubmission_tasks = [1222]
    for task_id in resubmission_tasks:
        response,status = prepare_api_submission.fetch_task_status(task_status_endpoint_url,task_id)
        assert status == 200
        print(response)
            
    task_groups = [[2233,9484,1222],[1197,1702,2764]]


#%% Pull results

task_id_to_results_file = {}

# i_task_group = 0; task_group = task_groups[i_task_group]; task_id = task_group[0]
for i_task_group,task_group in enumerate(task_groups):
    
    for task_id in task_group:
        
        response,status = prepare_api_submission.fetch_task_status(task_status_endpoint_url,task_id)
        assert status == 200

        output_file_urls = prepare_api_submission.get_output_file_urls(response)
        detections_url = output_file_urls['detections']
        fn = url_to_filename(detections_url)
        
        # n_failed_shards = int(response['status']['message']['num_failed_shards'])
        # assert n_failed_shards == 0
        
        # Each task group corresponds to one of our folders
        assert (folder_names[i_task_group] in fn) or \
            (prepare_api_submission.clean_request_name(folder_names[i_task_group]) in fn)
        assert 'chunk' in fn or 'missing' in fn
        
        output_file = os.path.join(raw_api_output_folder,fn)
        response = prepare_api_submission.download_url(detections_url,output_file)
        task_id_to_results_file[task_id] = output_file
        
    # ...for each task
        
# ...for each task group
 
    
#%% Combine results from task groups into final output files

folder_name_to_combined_output_file = {}

# i_folder = 0; folder_name = folder_names[i_folder]
for i_folder,folder_name in enumerate(folder_names):
    
    print('Combining results for {}'.format(folder_name))
    
    task_group = task_groups[i_folder]
    results_files = []
    
    # task_id = task_group[0]
    for task_id in task_group:
        
        raw_output_file = task_id_to_results_file[task_id]
        results_files.append(raw_output_file)
    
    combined_api_output_file = os.path.join(combined_api_output_folder,folder_name + '_detections.json')
    print('Combining the following into {}'.format(combined_api_output_file))
    for fn in results_files:
        print(fn)
        
    combine_api_outputs.combine_api_output_files(results_files,combined_api_output_file)
    folder_name_to_combined_output_file[folder_name] = combined_api_output_file

    # Check that we have (almost) all the images    
    list_file = list_files[i_folder]
    requested_images = json.load(open(list_file,'r'))
    results = json.load(open(combined_api_output_file,'r'))
    result_images = [im['file'] for im in results['images']]
    requested_images_set = set(requested_images)
    result_images_set = set(result_images)
    missing_files = requested_images_set - result_images_set
    missing_images = path_utils.find_image_strings(missing_files)
    if len(missing_images) > 0:
        print('Warning: {} missing images for folder {}'.format(len(missing_images),folder_name))    
    assert len(missing_images) < max_tolerable_missing_images

    # Something has gone bonkers if there are images in the results that
    # aren't in the request
    extra_images = result_images_set - requested_images_set
    assert len(extra_images) == 0
    
# ...for each folder
    
    
#%% Post-processing (no ground truth)

html_output_files = []

for i_folder,folder_name in enumerate(folder_names):
        
    output_base = os.path.join(postprocessing_output_folder,folder_name)
    os.makedirs(output_base,exist_ok=True)
    print('Processing {} to {}'.format(folder_name,output_base))
    api_output_file = folder_name_to_combined_output_file[folder_name]

    options = PostProcessingOptions()
    options.image_base_dir = image_base
    options.parallelize_rendering = True
    options.include_almost_detections = True
    options.num_images_to_sample = 5000
    options.confidence_threshold = 0.8
    options.almost_detection_confidence_threshold = 0.75
    options.ground_truth_json_file = None
    
    options.api_output_file = api_output_file
    options.output_dir = output_base
    ppresults = process_batch_results(options)
    html_output_files.append(ppresults.output_html_file)
    
for fn in html_output_files:
    os.startfile(fn)


#%% Timelapse prep 

data = None

from api.batch_processing.postprocessing.subset_json_detector_output import subset_json_detector_output
from api.batch_processing.postprocessing.subset_json_detector_output import SubsetJsonDetectorOutputOptions

input_filename = r"F:\blah.20190817.refiltered.json"
output_base = r"F:\blah\json_subsets_2019.08.17"
base_dir = r'Y:\Unprocessed Images'

folders = os.listdir(base_dir)

if data is None:
    with open(input_filename) as f:
        data = json.load(f)
        
print('Data set contains {} images'.format(len(data['images'])))

# i_folder = 0; folder_name = folders[i_folder]
for i_folder,folder_name in enumerate(folders):
    
    output_filename = os.path.join(output_base,folder_name + '.json')
    print('Processing folder {} of {} ({}) to {}'.format(i_folder,len(folders),folder_name,
          output_filename))
    
    options = SubsetJsonDetectorOutputOptions()
    options.confidence_threshold = 0.4
    options.overwrite_json_files = True
    options.make_folder_relative = True
    options.query = folder_name + '\\'
    
    subset_data = subset_json_detector_output(input_filename,output_filename,options,data)
