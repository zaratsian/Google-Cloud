
#############################################################################
#
#   Google Cloud Video Intelligence
#
#   Video Metadata Tagging + Streaming Insert to BigQuery
#
#   Usage:  file.py --youtube_url YOUTUBE_URL --bucket_name BUCKET_NAME --bq_dataset_id BQ_DATASET_ID --bq_table_id BQ_TABLE_ID
#           file.py --youtube_url=https://www.youtube.com/watch?v=imm6OR605UI --bucket_name=zmiscbucket1 --bq_dataset_id=video_analysis1 --bq_table_id=video_metadata1
#           file.py --youtube_url=https://www.youtube.com/watch?v=7dKownfx75E --bucket_name=zmiscbucket1 --bq_dataset_id=video_analysis1 --bq_table_id=video_metadata1
#
#   Dependencies:
#       pip install --upgrade google-cloud-videointelligence
#       pip install --upgrade google-cloud-storage
#       pip install --upgrade google-cloud-bigquery
#       pip install pytube
#
#   References:
#       https://cloud.google.com/video-intelligence/docs/
#       https://github.com/nficano/pytube
#       The Video Intelligence API supports common video formats, including .MOV, .MPEG4, .MP4, and .AVI
#
#############################################################################



from google.cloud import storage, bigquery, videointelligence
from pytube import YouTube
import argparse
import datetime, time
import requests
from bs4 import BeautifulSoup



def extract_url_title(url):
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('title').string
        print('[ INFO ] Successfully extracted Title: {}'.format(title))
        return title
    except:
        print('[ ERROR ] Issue processing URL. Check the URL and/or internet connection.')
        sys.exit()



def save_youtube_video(youtube_url):
    ''' Save Youtube Video to local machine as .mp4 '''
    
    youtube_id       = youtube_url.split('=')[-1]
    youtube_filename = "youtube_{}".format(youtube_id)
    output_path      = '/tmp'
    # Download Youtube Video, save locally
    YouTube(youtube_url) \
        .streams \
        .filter(progressive=True, file_extension='mp4') \
        .first() \
        .download(output_path=output_path, filename=youtube_filename)
    
    local_filepath = "{}/{}.mp4".format(output_path, youtube_filename)
    print('[ INFO ] Complete! Youtube video downloaded to {}'.format(local_filepath))
    return local_filepath



def upload_to_gcs(bucket_name, local_filepath):
    ''' Upload local file (.mp4) to Google Cloud Storage '''
    
    gcs_blob_name  = local_filepath.split('/')[-1]
    gcs_filepath   = 'gs://{}/{}'.format(bucket_name, gcs_blob_name)
    
    storage_client = storage.Client()
    gcs_bucket     = storage_client.get_bucket(bucket_name)    
    gcs_blob       = gcs_bucket.blob(gcs_blob_name)
    gcs_blob.upload_from_filename(local_filepath)
    print('[ INFO ] File {} uploaded to {}'.format(
        local_filepath,
        gcs_filepath))
    return gcs_filepath



def process_video_in_gcs(gcs_filepath, video_url, title):
    ''' Apply Google Video Intelligence API - Tag video metadata shot-by-shot '''
    
    print('[ INFO ] Processing video at {}'.format(gcs_filepath))
    processing_start_time = datetime.datetime.now()
    print('[ INFO ] Start time: {}'.format(processing_start_time.strftime("%Y-%m-%d %H:%M:%S")) )
    
    video_client = videointelligence.VideoIntelligenceServiceClient()
    features     = [videointelligence.enums.Feature.LABEL_DETECTION]
    operation    = video_client.annotate_video(gcs_filepath, features=features)
    result       = operation.result(timeout=600)
    
    segment_labels = result.annotation_results[0].segment_label_annotations
    shots = result.annotation_results[0].shot_label_annotations
    
    # Not needed, the following code will parse this content in a different way
    #shot_metadata = {}
    #for shot in shots:
    #    entity   = shot.entity.description
    #    #category = shot.category_entities[0].description
    #    segments = shot.segments
    #    shot_metadata[entity] = { "count": len(list(segments)), "shot_segments":list(segments) }
    
    shot_records = []
    for shot in shots:
        datetimeid = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        entity     = shot.entity.description
        try:
            category = shot.category_entities[0].description
        except:
            category = ''
        segments = shot.segments
        for segment in segments:
            start_time_offset   = segment.segment.start_time_offset.seconds   # Seconds
            start_time_offset_m = int(start_time_offset / 60)
            start_time_offset_s = start_time_offset % 60
            end_time_offset     = segment.segment.end_time_offset.seconds
            confidence          = segment.confidence
            video_url_at_time   = video_url+'&t={}m{}s'.format(start_time_offset_m, start_time_offset_s)
            shot_records.append( (datetimeid, title, video_url_at_time, gcs_filepath, entity, category, start_time_offset, end_time_offset, confidence) )
    
    print('[ INFO ] Processing complete. There were {} shot records found.'.format(len(shot_records)))
    processing_end_time = datetime.datetime.now()
    print('[ INFO ] End time: {}'.format(processing_end_time.strftime("%Y-%m-%d %H:%M:%S")) )
    print('[ INFO ] Run time: {} seconds'.format((processing_end_time - processing_start_time).seconds) )
    return shot_records



def bg_streaming_insert(rows_to_insert, bq_dataset_id, bq_table_id):
    ''' BigQuery Streaming Insert - Insert python list into BQ '''
    
    # Note: The table must already exist and have a defined schema
    # rows_to_insert is a list of variables (i.e. (id, date, value1, value2, etc.))
    print('[ INFO ] Inserting records in BigQuery')
    client    = bigquery.Client()
    table_ref = client.dataset(bq_dataset_id).table(bq_table_id)
    table     = client.get_table(table_ref)  
    errors    = client.insert_rows(table, rows_to_insert)
    if errors == []:
        print('[ INFO ] Complete. No errors on Big Query insert')



if __name__ == "__main__":
    
    # ONLY used for TESTING - Example Arguments
    #args =  {
    #           "youtube_url":   "https://www.youtube.com/watch?v=imm6OR605UI",
    #           "bucket_name":   "zmiscbucket1",
    #           "bq_dataset_id": "video_analysis1",
    #           "bq_table_id":   "video_metadata1"
    #       }
    
    # Arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("--youtube_url", required=True, help="YouTube URL")
    ap.add_argument("--bucket_name", required=True, help="Google Cloud Storage bucket name")
    ap.add_argument("--bq_dataset_id", required=True, help="Google BigQuery Dataset ID")
    ap.add_argument("--bq_table_id", required=True, help="Google BigQuery Table ID")
    args = vars(ap.parse_args())
    
    # Extract YouTube page Title 
    title = extract_url_title(url=args["youtube_url"])
    
    # Download Youtube video as .mp4 file to local
    local_filepath = save_youtube_video(args["youtube_url"])
    
    # Upload .mp4 file to Google Cloud Storage (GCS)
    gcs_filepath = upload_to_gcs(args["bucket_name"], local_filepath)
    
    # Process .mp4 video file, stored on Google Cloud Storage (GCS)
    shot_records = process_video_in_gcs(gcs_filepath=gcs_filepath, video_url=args["youtube_url"], title=title)
    
    # Insert into BigQuery
    bg_streaming_insert(rows_to_insert=shot_records, bq_dataset_id=args['bq_dataset_id'], bq_table_id=args['bq_table_id'])







"""

#############################################################################
#
#   BigQuery Setup
#
#############################################################################



from google.cloud import bigquery


def bq_create_dataset(dataset_id):
    ''' Create BigQuery Dataset '''
    
    bigquery_client = bigquery.Client()
    dataset_ref     = bigquery_client.dataset(dataset_id)
    dataset         = bigquery.Dataset(dataset_ref)
    dataset         = bigquery_client.create_dataset(dataset)
    print('[ INFO ] Dataset {} created.'.format(dataset.dataset_id))


table_schema = [
    bigquery.SchemaField('datetimeid',          'STRING',   mode='REQUIRED'),
    bigquery.SchemaField('title',               'STRING',   mode='NULLABLE'),
    bigquery.SchemaField('video_url',           'STRING',   mode='NULLABLE'),
    bigquery.SchemaField('gcs_url',             'STRING',   mode='NULLABLE'),
    bigquery.SchemaField('entity',              'STRING',   mode='NULLABLE'),
    bigquery.SchemaField('category',            'STRING',   mode='NULLABLE'),
    bigquery.SchemaField('start_time_seconds',  'INTEGER',  mode='NULLABLE'),
    bigquery.SchemaField('end_time_seconds',    'INTEGER',  mode='NULLABLE'),
    bigquery.SchemaField('confidence',          'FLOAT',    mode='NULLABLE'),
]


def bq_create_table(dataset_id, table_id, table_schema):
    ''' Create BigQuery Table '''
    
    #table_schema = [
    #    bigquery.SchemaField('full_name', 'STRING', mode='REQUIRED'),
    #    bigquery.SchemaField('age', 'INTEGER', mode='REQUIRED'),
    #]
    
    # BigQuery Client
    bigquery_client = bigquery.Client()
    
    # Dataset object
    dataset_ref     = bigquery_client.dataset(dataset_id)
    
    # Table object and creation
    table_ref       = dataset_ref.table(table_id)
    table           = bigquery.Table(table_ref, schema=table_schema)
    table           = bigquery_client.create_table(table)
    print('[ INFO ] Table {} created.'.format(table.table_id))


bq_create_table('video_analysis1', 'video_metadata1', table_schema)


def bq_query_table(query):
    ''' BigQuery Query Table '''
    
    bigquery_client = bigquery.Client()
    
    #query = ('''select * from video_analysis1.video_metadata1 limit 5''')
    
    query_job = bigquery_client.query(
        query,
        # Location must match that of the dataset(s) referenced in the query.
        location='US')  # API request - starts the query
    
    # Print Results
    for row in query_job:
        # Row values can be accessed by field name or index
        # NOTE: row[0] == row.name == row['name']
        print(row)


query = ('''select * from video_analysis1.video_metadata1 limit 5''')
bq_query_table(query)


#ZEND


"""






#ZEND
