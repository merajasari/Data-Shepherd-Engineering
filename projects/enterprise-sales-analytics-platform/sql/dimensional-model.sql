-- Enterprise Sales Analytics Dimensional Model

CREATE TABLE DimCustomer (
    CustomerKey INT PRIMARY KEY,
    CustomerId VARCHAR(50),
    CustomerName VARCHAR(200),
    Region VARCHAR(100),
    EffectiveDate DATE,
    ExpirationDate DATE,
    IsCurrent BIT
);

CREATE TABLE DimProduct (
    ProductKey INT PRIMARY KEY,
    ProductId VARCHAR(50),
    ProductName VARCHAR(200),
    Category VARCHAR(100)
);

CREATE TABLE FactSales (
    SalesKey BIGINT PRIMARY KEY,
    CustomerKey INT,
    ProductKey INT,
    SalesDate DATE,
    Quantity INT,
    SalesAmount DECIMAL(18,2)
);

-- Example star schema supporting enterprise reporting
