# Data Quality Checks

## Validation Rules

### Completeness
- Required business keys cannot be null
- Customer and product references must exist

### Accuracy
- Sales amount must be greater than or equal to zero
- Transaction dates cannot be future dates

### Uniqueness
- TransactionId must be unique

### Monitoring

Recommended tools:
- Azure Monitor
- Log Analytics
- Microsoft Fabric monitoring
- Databricks job monitoring
