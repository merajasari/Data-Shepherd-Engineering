from pyspark.sql.functions import col, current_timestamp

# Read Bronze layer data
bronze_df = spark.read.format("delta").load("/bronze/sales")

# Basic cleansing and standardization
silver_df = (
    bronze_df
    .dropDuplicates(["TransactionId"])
    .filter(col("SalesAmount") >= 0)
    .withColumn("ProcessedDate", current_timestamp())
)

# Write Silver Delta table
silver_df.write.format("delta").mode("overwrite").save("/silver/sales")
