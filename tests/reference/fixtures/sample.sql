CREATE TABLE analytics.fct_orders (
    order_id NUMBER(38,0),
    customer_id NUMBER(38,0)
);

CREATE VIEW analytics.v_active_customers AS
SELECT customer_id
FROM analytics.dim_customers c
JOIN analytics.fct_orders o ON o.customer_id = c.customer_id;

INSERT INTO analytics.audit_log SELECT 1;
