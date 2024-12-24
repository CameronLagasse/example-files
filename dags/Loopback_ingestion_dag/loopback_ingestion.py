from dagster import (
    job,
    op,
    DynamicOut,
    DynamicOutput,
    ResourceDefinition,
    sensor,
    RunRequest,
    DefaultSensorStatus,
    Definitions,
    SkipReason,
    DagsterRunStatus,
    RunsFilter,
)
from dagster_k8s import k8s_job_executor
from google.cloud import storage, bigquery
import os
import gzip
import snowflake.connector
import subprocess
import urllib.parse
import json
from typing import List
import pandas as pd


# Load configuration file
def load_config(config_file_path="config.json"):
    try:
        with open(config_file_path, mode="r") as file:
            config = json.load(file)
        return config
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found at {config_file_path}")
    except json.JSONDecodeError:
        raise ValueError(f"Error decoding JSON from config file: {config_file_path}")
    except Exception as e:
        raise Exception(f"An error occurred while reading {config_file_path}: {str(e)}")


############# DEFINE GLOBAL VARIABLES ################
# Config json file path
config_file_path = "/app/dagster_pipeline/config.json"

# Snowflake DB variables
db_user = os.getenv("SNOWFLAKE_USER")
db_password = os.getenv("SNOWFLAKE_PASSWORD")
db_account = os.getenv("SNOWFLAKE_ACCOUNT")

# Chunk size for download op
chunk_size = 500000  # Number of rows to fetch at a time

# Max file size
max_size_bytes = 3 * 1024 * 1024 * 1024  # 3GB

# Directory where files are saved
data_dir = "/opt/dagster/dagster_home/storage"

# Google setup variables
google_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not google_creds:
    raise EnvironmentError(
        "GOOGLE_APPLICATION_CREDENTIALS environment variable not set."
    )

storage_client = storage.Client()  # Authenticated using GOOGLE_APPLICATION_CREDENTIALS

config = load_config("/app/dagster_pipeline/config.json")
bucket_name = config.get("options", {}).get("bucket_name")
dataset_name = config.get("options", {}).get("dataset_name")
project_id = config.get("options", {}).get("project_id")

# Dagster K8s Executor config
k8s_executor_config = config.get("k8s_executor_config", {})
# Define the executor using the config
k8s_executor = k8s_job_executor.configured(k8s_executor_config)
############## END OF GLOBAL VARIABLES #####################


# Define the operation that yields dynamic outputs for each table
@op(out=DynamicOut())
def select_tables(context):

    try:
        # Load the config file using the load_config function
        config = load_config(config_file_path)

        # Extract the list of tables from the config
        sftable = config.get("tables", [])
        context.log.info(f"Read {len(sftable)} table(s) from {config_file_path}.")

    except Exception as e:
        context.log.error(f"Error reading {config_file_path}: {e}")
        sftable = []

    # Yield dynamic outputs for each table name
    for table in sftable:
        context.log.info(f"Yielding dynamic output for table: {table}")
        yield DynamicOutput(value=table, mapping_key=table)


# Define the operation that yields dynamic outputs for each table
@op(out=DynamicOut())
def select_small_tables(context):

    try:
        # Load the config file using the load_config function
        config = load_config(config_file_path)

        # Extract the list of tables from the config
        sftable = config.get("small_tables", [])
        context.log.info(f"Read {len(sftable)} table(s) from {config_file_path}.")

    except Exception as e:
        context.log.error(f"Error reading {config_file_path}: {e}")
        sftable = []

    # Yield dynamic outputs for each table name
    for small_table in sftable:
        context.log.info(f"Yielding dynamic output for table: {small_table}")
        yield DynamicOutput(value=small_table, mapping_key=small_table)


# Define the operation to download data for a specific table
@op
def download_from_snowflake(context, table_name: str) -> str:

    # Establish BigQuery connection
    bq_client = bigquery.Client(project=project_id)

    # Query to fetch the latest DATAREFRESHID from BigQuery
    latest_refreshid_query = f"""
        SELECT DATAREFRESHID
        FROM `{project_id}.{dataset_name}.{table_name}`
        ORDER BY DATAREFRESHID DESC
        LIMIT 1
    """
    latest_refreshid = None

    try:
        # Run the query to get the latest DATAREFRESHID
        query_job = bq_client.query(latest_refreshid_query)
        latest_refreshid_result = query_job.result()

        # If there's a result, get the latest DATAREFRESHID
        if latest_refreshid_result.total_rows > 0:
            latest_refreshid = list(latest_refreshid_result)[0].DATAREFRESHID
        context.log.info(f"Latest DATAREFRESHID from BigQuery: {latest_refreshid}")

    except Exception as e:
        context.log.error(f"Failed to get latest DATAREFRESHID from BigQuery: {e}")

    # Establish Snowflake connection
    conn = snowflake.connector.connect(
        user=db_user,
        password=db_password,
        account=db_account,
    )

    # Query to select rows from Snowflake where DATAREFRESHID > latest_refreshid (if it exists)
    if latest_refreshid is not None:
        query = f"""
            SELECT * 
            FROM DEID_ROIVANT.SOW2.{table_name}
            WHERE DATAREFRESHID > {latest_refreshid}
        """
    else:
        # If no latest_refreshid found, fetch all rows from Snowflake (first run)
        query = f"SELECT * FROM DEID_ROIVANT.SOW2.{table_name};"

    context.log.info(f"Started download of table: {table_name}")

    # Create a cursor and execute the query
    cursor = conn.cursor()
    cursor.execute(query)

    # File path to save the data
    file_path = f"/opt/dagster/dagster_home/storage/{table_name}.csv.gz"

    # Create a gzip file to stream and save the data
    with gzip.open(file_path, "wt") as gz_file:
        # Write header (column names) to the file
        columns = [col[0] for col in cursor.description]
        gz_file.write("|".join(columns) + "\n")

        # Fetch data in chunks and write each chunk to the gzipped CSV
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break  # Break when there are no more rows

            # Convert the chunk into a Pandas DataFrame
            df_chunk = pd.DataFrame(rows, columns=columns)

            # Clean the data: Replace null bytes and "None" in one operation
            df_chunk.replace(
                to_replace=[r"\x00", r"None"], value="", regex=True, inplace=True
            )

            # Write each chunk to the gzipped CSV file
            df_chunk.to_csv(
                gz_file, sep="|", header=False, index=False, escapechar="\\"
            )

    context.log.info(f"Downloaded and saved: {file_path}")

    # Close the cursor and connection
    cursor.close()
    conn.close()

    return file_path  # Return the file path for downstream ops


# Define the operation to download data for a specific table
@op
def download_from_snowflake_small_tables(context, table_name: str):
    # Establish Snowflake connection
    conn = snowflake.connector.connect(
        user=db_user,
        password=db_password,
        account=db_account,
    )

    # Query to fetch the latest DATAREFRESHID from BigQuery for this table
    latest_refreshid_query = f"SELECT DATAREFRESHID FROM `{project_id}.{dataset_name}.{table_name}` ORDER BY DATAREFRESHID DESC LIMIT 1"

    # Create a BigQuery client to get the latest DATAREFRESHID
    bq_client = bigquery.Client(project=project_id)
    latest_refreshid = None

    try:
        # Run the query to get the latest DATAREFRESHID
        query_job = bq_client.query(latest_refreshid_query)
        latest_refreshid_result = query_job.result()

        # If there's a result, get the latest DATAREFRESHID
        if latest_refreshid_result.total_rows > 0:
            latest_refreshid = list(latest_refreshid_result)[0].DATAREFRESHID
        context.log.info(f"Latest DATAREFRESHID from BigQuery: {latest_refreshid}")

    except Exception as e:
        context.log.error(f"Failed to get latest DATAREFRESHID from BigQuery: {e}")

    # Query to select rows from Snowflake where DATAREFRESHID > latest_refreshid (if it exists)
    if latest_refreshid is not None:
        query = f"""
            SELECT DATAREFRESHID,REFRESHEDON 
            FROM DEID_ROIVANT.SOW2.{table_name}
            WHERE DATAREFRESHID > {latest_refreshid}
        """
    else:
        # If no latest_refreshid found, fetch all rows from Snowflake (first run)
        query = f"SELECT DATAREFRESHID,REFRESHEDON FROM DEID_ROIVANT.SOW2.{table_name};"

    context.log.info(f"Started download of table: {table_name}")

    # Create a cursor and execute the query
    cursor = conn.cursor()
    cursor.execute(query)

    # File path to save the data
    file_path = f"/opt/dagster/dagster_home/storage/{table_name}.csv.gz"

    # Create a gzip file to stream and save the data
    with gzip.open(file_path, "wt") as gz_file:
        # Write header (column names) to the file
        columns = [col[0] for col in cursor.description]
        gz_file.write("|".join(columns) + "\n")

        # Fetch data in chunks and write each chunk to the gzipped CSV
        while True:
            rows = cursor.fetchall()
            if not rows:
                break  # Break when there are no more rows

            # Convert the chunk into a Pandas DataFrame
            df_chunk = pd.DataFrame(rows, columns=columns)

            # Clean the data: Replace null bytes and "None" in one operation
            df_chunk.replace(
                to_replace=[r"\x00", r"None"], value="", regex=True, inplace=True
            )

            # Write each chunk to the gzipped CSV file
            df_chunk.to_csv(
                gz_file, sep="|", header=False, index=False, escapechar="\\"
            )

    context.log.info(f"Downloaded and saved: {file_path}")

    # Close the cursor and connection
    cursor.close()
    conn.close()

    return [file_path]  # Return the file path for downstream ops


# File Chunking Operation
@op
def chunk_large_files(context, file_name: str):

    file_size = os.path.getsize(file_name)

    if file_size > max_size_bytes:
        context.log.info(f"Processing large file: {file_name}")

        # Decompress the file
        subprocess.run(["pigz", "-d", file_name])
        base_file_path = file_name[:-3]  # Remove the .gz extension from the path

        # Get the base name without the directory, .gz, and .csv extensions
        base_name = os.path.basename(file_name)  # Get the file name with extensions
        base_name = os.path.splitext(base_name)[0]  # Remove the .gz extension
        base_name = os.path.splitext(base_name)[0]  # Remove the .csv extension

        # Count total lines in the decompressed file
        total_lines = sum(1 for line in open(base_file_path))
        lines_per_split = int(total_lines * max_size_bytes / file_size)

        # Split the file into smaller parts
        context.log.info(f"Splitting {base_name} into smaller parts")
        subprocess.run(
            [
                "split",
                "-l",
                str(lines_per_split),
                base_file_path,
                os.path.join(data_dir, f"{base_name}.part"),
            ]
        )

        # Rename split files to match the required format and compress them
        split_files = [
            f for f in os.listdir(data_dir) if f.startswith(f"{base_name}.part")
        ]

        if split_files:
            renamed_files = []
            for idx, split_file in enumerate(sorted(split_files), start=1):
                split_file_path = os.path.join(data_dir, split_file)
                new_name = os.path.join(data_dir, f"{base_name}.part{idx}.csv")
                os.rename(split_file_path, new_name)

                # Compress the renamed file
                subprocess.run(["pigz", new_name])
                context.log.info(f"Split and compressed: {new_name}.gz")
                renamed_files.append(f"{new_name}.gz")

            # Clean up the decompressed file
            os.remove(base_file_path)
            context.log.info(f"Removed {base_file_path} from share directory")

            # Return the list of renamed and compressed files
            return renamed_files
        else:
            context.log.error(
                f"No split files created for {file_name}. Something went wrong."
            )
    else:
        context.log.info(f"{file_name} does not need to be split")
        return [
            file_name
        ]  # Return the original compressed file if no splitting was required


# Save to GCS Operation
@op
def save_to_gcs(context, table_name: list) -> List[str]:

    context.log.info("Authenticated to Google Cloud")
    gcs_paths = []  # Collect GCS object paths to return

    for file_name in table_name:
        file_path = os.path.join(data_dir, file_name)  # Construct the full path
        context.log.info(f"Full file name: {file_path}")

        if not os.path.exists(file_path):
            context.log.error(f"File {file_name} does not exist.")
            continue

        base_file_name = os.path.basename(file_path)  # Extract the file name
        folder_name = base_file_name.split(".")[0]  # Extract the table name
        folder_name = folder_name.replace(".csv.gz", "")
        context.log.info(f"Local folder name is {folder_name}")
        gcs_object_path = (
            f"Loopback/{dataset_name}/{folder_name}/{base_file_name}".strip("/")
        )

        # Upload the file to GCS
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(gcs_object_path)

        try:
            blob.upload_from_filename(file_path)
            context.log.info(f"Uploaded file {file_name} to GCS at {gcs_object_path}")
            os.remove(file_path)
            context.log.info(f"Cleaned up and deleted {file_path}")

            # Add the GCS object path to the list of outputs
            gcs_paths.append(gcs_object_path)
        except Exception as e:
            context.log.error(f"Failed to upload {file_name} to GCS: {e}")
            raise

    return gcs_paths


# BigQuery Load Operation
@op
def load_to_bigquery(context, gcs_object_paths: List[str]):

    context.log.info("Authenticated to GCP")

    # Process each GCS object path
    for gcs_object_path in gcs_object_paths:
        # Derive table name from GCS object path
        table_name = gcs_object_path.split("/")[-2]
        context.log.info(f"Processing table: {table_name}")

        # Download schema from GCS
        schema_name = (
            table_name.replace("VW_DEID_", "")
            .replace("_INCREMENTAL", "")
            .replace("VW_DATA_", "")
            + ".json"
        )
        context.log.info(f"Schema name: {schema_name}")
        schema_file_gcs_path = f"schemas/{schema_name}"
        context.log.info(f"Schema GCS Path: {schema_file_gcs_path}")
        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(schema_file_gcs_path)
        local_schema_file = f"./{schema_name}"
        context.log.info(f"Local schema file: {local_schema_file}")

        try:
            blob.download_to_filename(local_schema_file)
            context.log.info(f"Downloaded schema file: {schema_file_gcs_path}")
        except Exception as e:
            context.log.error(f"Schema file {schema_name} not found: {e}")
            continue

        # Load schema from the downloaded file
        with open(local_schema_file, "r") as schema_file:
            schema_data = json.load(schema_file)
            schema = [
                bigquery.SchemaField.from_api_repr(field) for field in schema_data
            ]
        context.log.info(f"Schema: {schema}")
        # Configure the BigQuery load job
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            field_delimiter="|",
            skip_leading_rows=1,
            max_bad_records=10,
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,  # Important: appends rows
        )

        # Perform the load job
        gcs_uri = f"gs://{bucket_name}/{gcs_object_path}"
        table_id = f"{dataset_name}.{table_name}"
        bq_client = bigquery.Client(project=project_id)
        load_job = bq_client.load_table_from_uri(
            gcs_uri, table_id, job_config=job_config
        )
        load_job.result()

        context.log.info(f"Loaded {load_job.output_rows} rows into {table_id}.")

        # Clean up
        os.remove(local_schema_file)
        context.log.info(f"Deleted local schema file: {local_schema_file}")


# Define the pipeline
@job(executor_def=k8s_executor)
def loopback_ingestion_pipeline():
    # Step 1: Get the list of tables dynamically
    tables = select_tables()

    small_tables = select_small_tables()

    # Step 2: Download files for each table concurrently
    downloaded_files = tables.map(download_from_snowflake)
    downloaded_small_files = small_tables.map(download_from_snowflake_small_tables)

    # Step 2: Chunk the downloaded files
    chunked_files = downloaded_files.map(chunk_large_files)

    # Step 3: Save the chunks to GCS and collect GCS paths
    gcs_paths = chunked_files.map(save_to_gcs)
    gcs_paths_small = downloaded_small_files.map(save_to_gcs)

    # Step 4: Load the saved chunks into BigQuery using GCS paths
    gcs_paths.map(load_to_bigquery)
    gcs_paths_small.map(load_to_bigquery)


@sensor(target=loopback_ingestion_pipeline, default_status=DefaultSensorStatus.RUNNING)
def check_snowflake_for_updates_sensor(context):
    try:
        # Query Snowflake for the latest DATAREFRESHID
        conn = snowflake.connector.connect(
            user=db_user,
            password=db_password,
            account=db_account,
        )

        table_name = "VW_DATA_REFRESHES"

        cursor = conn.cursor()
        snowflake_query = f"SELECT MAX(DATAREFRESHID) AS LATEST_ID FROM DEID_ROIVANT.SOW2.{table_name};"
        cursor.execute(snowflake_query)
        snowflake_latest_id = cursor.fetchone()[0]  # Fetch the first row, first column
        context.log.info(f"Latest DATAREFRESHID from Snowflake: {snowflake_latest_id}")

        # Query BigQuery for the current maximum DATAREFRESHID
        bq_client = bigquery.Client(project=project_id)
        bq_query = f"SELECT MAX(DATAREFRESHID) AS LATEST_ID FROM `{project_id}.{dataset_name}.{table_name}`;"
        query_job = bq_client.query(bq_query)
        result = list(query_job.result())

        # If no data is returned from BigQuery, set bq_latest_id to 0
        bq_latest_id = (
            result[0].LATEST_ID if result and result[0].LATEST_ID is not None else 0
        )
        context.log.info(f"Latest DATAREFRESHID from BigQuery: {bq_latest_id}")

        # Compare Snowflake and BigQuery IDs
        if snowflake_latest_id > bq_latest_id:
            context.log.info("New data found in Snowflake. Checking for existing runs.")

            # Use a unique run_key based on the Snowflake latest ID
            run_key = f"refresh_id_{snowflake_latest_id}"

            # Check if there's an active or completed run with this run_key
            runs_filter = RunsFilter(tags={"dagster/run_key": run_key})
            existing_runs = context.instance.get_runs(filters=runs_filter)

            if any(
                run.status
                in [
                    DagsterRunStatus.STARTING,
                    DagsterRunStatus.STARTED,
                    DagsterRunStatus.SUCCESS,
                ]
                for run in existing_runs
            ):
                context.log.info(
                    f"Job already running or completed for refresh_id: {snowflake_latest_id}"
                )
                return SkipReason(
                    "A job is already running or completed for this DATAREFRESHID."
                )

            # Trigger the job with any required configuration
            return RunRequest(
                run_key=run_key,  # Ensures no overlapping runs
                run_config={},
            )
        else:
            context.log.info("No new data found in Snowflake.")
            return SkipReason("No new data in Snowflake.")

    except Exception as e:
        context.log.error(f"Error in sensor: {e}")
        return None  # No job triggered in case of error


defs = Definitions(
    jobs=[loopback_ingestion_pipeline],
    sensors=[check_snowflake_for_updates_sensor],
)
