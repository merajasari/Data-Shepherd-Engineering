# Enterprise Sales Analytics Platform

## Overview

A cloud-scale analytics platform demonstrating enterprise Azure Data Engineering patterns using Microsoft Azure, Microsoft Fabric, Databricks, Delta Lake, Synapse, and Power BI.

## Architecture

Source Systems
- SQL Server transactional databases
- Oracle systems
- CSV/API data feeds

Pipeline Flow

Sources -> Azure Data Factory -> ADLS Gen2 / OneLake -> Bronze -> Silver -> Gold -> Synapse -> Power BI

## Technologies

- Azure Data Factory
- Azure Data Lake Storage Gen2
- Microsoft Fabric OneLake
- Azure Databricks
- Apache Spark
- Delta Lake
- Azure Synapse Analytics
- Power BI
- SQL Server
- Python

## Data Engineering Concepts Demonstrated

- Medallion Architecture
- Incremental data loading
- Slowly Changing Dimensions
- Data quality validation
- Metadata-driven pipelines
- Security with managed identities
- Monitoring and logging

## Future Additions

- ADF pipeline examples
- PySpark notebooks
- SQL dimensional models
- Sample datasets
- CI/CD deployment examples
