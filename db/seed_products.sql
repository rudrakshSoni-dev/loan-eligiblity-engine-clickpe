INSERT INTO loan_products AS p (
    source, product_name, source_url,
    interest_rate_min, interest_rate_max, min_monthly_income,
    min_credit_score, max_credit_score, min_age, max_age,
    allowed_employment, raw_criteria_text, content_hash, parse_confidence, is_seed
)
SELECT
    'seed', v.product_name, NULL,
    v.rate_min, v.rate_max, v.min_income,
    v.min_score, v.max_score, v.min_age, v.max_age,
    v.employment, v.criteria,
    encode(sha256(convert_to(v.criteria, 'UTF8')), 'hex'),
    1.0,
    true
FROM (VALUES
    ('Seed · Salaried Personal Loan', 10.50, 16.00, 30000, 700, NULL, 21, 58,
     ARRAY['Salaried'],
     'SEED DATA. Salaried applicants aged 21 to 58. Minimum net monthly income Rs 30,000. '
     'Credit score 700 or above. Interest 10.50% to 16.00% p.a.'),
    ('Seed · Self-Employed Personal Loan', 12.00, 20.00, 40000, 725, NULL, 25, 60,
     ARRAY['Self-Employed', 'Business'],
     'SEED DATA. Self-employed professionals and business owners aged 25 to 60. Minimum '
     'monthly income Rs 40,000. Credit score 725 or above. Interest 12.00% to 20.00% p.a.'),
    ('Seed · Premium Personal Loan', 9.99, 12.50, 100000, 775, NULL, 25, 55,
     ARRAY['Salaried'],
     'SEED DATA. Salaried applicants aged 25 to 55. Minimum net monthly income Rs 1,00,000. '
     'Credit score 775 or above. Interest 9.99% to 12.50% p.a.'),
    ('Seed · Starter Personal Loan', 16.00, 24.00, 25000, 650, 749, 21, 40,
     NULL,
     'SEED DATA. Any employment type, aged 21 to 40. Minimum monthly income Rs 25,000. '
     'For credit scores from 650 to 749. Interest 16.00% to 24.00% p.a.'),
    ('Seed · Business Loan Lite', 14.00, 22.00, 50000, 700, NULL, 24, 65,
     ARRAY['Business'],
     'SEED DATA. Business owners aged 24 to 65 with at least 2 years of business vintage. '
     'Minimum monthly income Rs 50,000. Credit score 700 or above. Interest 14.00% to 22.00% p.a.')
) AS v (product_name, rate_min, rate_max, min_income, min_score, max_score, min_age, max_age,
        employment, criteria)
ON CONFLICT (source, product_name) DO UPDATE SET
    interest_rate_min  = EXCLUDED.interest_rate_min,
    interest_rate_max  = EXCLUDED.interest_rate_max,
    min_monthly_income = EXCLUDED.min_monthly_income,
    min_credit_score   = EXCLUDED.min_credit_score,
    max_credit_score   = EXCLUDED.max_credit_score,
    min_age            = EXCLUDED.min_age,
    max_age            = EXCLUDED.max_age,
    allowed_employment = EXCLUDED.allowed_employment,
    raw_criteria_text  = EXCLUDED.raw_criteria_text,
    content_hash       = EXCLUDED.content_hash,
    parse_confidence   = EXCLUDED.parse_confidence
WHERE p.is_seed
  AND (p.interest_rate_min, p.interest_rate_max, p.min_monthly_income,
       p.min_credit_score, p.max_credit_score, p.min_age, p.max_age,
       p.allowed_employment, p.content_hash, p.parse_confidence)
      IS DISTINCT FROM
      (EXCLUDED.interest_rate_min, EXCLUDED.interest_rate_max, EXCLUDED.min_monthly_income,
       EXCLUDED.min_credit_score, EXCLUDED.max_credit_score, EXCLUDED.min_age, EXCLUDED.max_age,
       EXCLUDED.allowed_employment, EXCLUDED.content_hash, EXCLUDED.parse_confidence);
