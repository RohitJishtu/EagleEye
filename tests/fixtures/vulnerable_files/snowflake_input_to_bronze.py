# Vulnerable fixture: integer overflow — MaxRowID cast as int (max ~2.1B)
# Should be .cast("long") to match NUMBER(38,0) schema in DDL

from pyspark.sql import functions as F

def read_incremental(spark, config):
    df = spark.read.format("snowflake").options(**config).load()
    # BUG: cast("int") overflows for ROWID values > 2,147,483,647
    return df.withColumn("MaxRowID", F.col("ROWID").cast("int"))
