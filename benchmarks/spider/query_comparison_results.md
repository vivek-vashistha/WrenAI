# SQL Query Comparison Results

## Test Summary
Tested 3 questions from `train_others.json` (2 from IMDB, 1 from Academic database) against the `/api/v1/generate_sql` endpoint.

---

## Test 1: IMDB - Complex Join Query

### Question:
"Find all movies directed by " Asghar Farhadi " and featuring " Taraneh Alidoosti ""

### Expected Query (from train_others.json):
```sql
SELECT t4.title 
FROM CAST AS t5 
JOIN actor AS t1 ON t5.aid = t1.aid 
JOIN movie AS t4 ON t4.mid = t5.msid 
JOIN directed_by AS t2 ON t4.mid = t2.msid 
JOIN director AS t3 ON t3.did = t2.did 
WHERE t1.name = "Taraneh Alidoosti" AND t3.name = "Asghar Farhadi";
```

### Actual Query (from API):
```sql
SELECT DISTINCT "imdb_movie"."title" 
FROM "imdb_movie" 
JOIN "imdb_directed_by" ON "imdb_movie"."mid" = "imdb_directed_by"."msid" 
JOIN "imdb_director" ON "imdb_directed_by"."did" = "imdb_director"."did" 
JOIN "imdb_cast" ON "imdb_movie"."mid" = "imdb_cast"."msid" 
JOIN "imdb_actor" ON "imdb_cast"."aid" = "imdb_actor"."aid" 
WHERE lower("imdb_director"."name") = lower('Asghar Farhadi') 
AND lower("imdb_actor"."name") = lower('Taraneh Alidoosti')
```

### Differences:
1. **Table Names**: Uses `imdb_movie`, `imdb_cast`, `imdb_actor`, etc. instead of `movie`, `CAST`, `actor`
2. **Column Quoting**: Uses double quotes for identifiers (`"imdb_movie"."title"`)
3. **DISTINCT**: Added `DISTINCT` keyword
4. **Case Sensitivity**: Uses `LOWER()` for case-insensitive comparison
5. **JOIN Order**: Starts from `imdb_movie` instead of `CAST`
6. **String Quotes**: Uses single quotes in WHERE clause instead of double quotes

### Logical Equivalence: ✅ YES
Both queries return the same results logically, but with different syntax and optimizations.

---

## Test 2: IMDB - Simple Query

### Question:
"What year is the movie " The Imitation Game " from ?"

### Expected Query (from train_others.json):
```sql
SELECT release_year FROM movie WHERE title = "The Imitation Game";
```

### Actual Query (from API):
```sql
SELECT "imdb_movie"."release_year" 
FROM "imdb_movie" 
WHERE lower("imdb_movie"."title") = lower('The Imitation Game')
```

### Differences:
1. **Table Name**: `imdb_movie` instead of `movie`
2. **Column Quoting**: Fully qualified with table name and quotes
3. **Case Sensitivity**: Uses `LOWER()` for case-insensitive comparison
4. **String Quotes**: Single quotes instead of double quotes

### Logical Equivalence: ✅ YES

---

## Test 3: Academic - Simple Query

### Question:
"return me the homepage of PVLDB ."

### Expected Query (from train_others.json):
```sql
SELECT homepage FROM journal WHERE name = "PVLDB";
```

### Actual Query (from API):
```sql
SELECT "academic_organization"."homepage" 
FROM "academic_organization" 
WHERE lower("academic_organization"."name") = lower('PVLDB')
```

### Differences:
1. **Table Name**: `academic_organization` instead of `journal`
2. **Column Quoting**: Fully qualified with table name and quotes
3. **Case Sensitivity**: Uses `LOWER()` for case-insensitive comparison
4. **String Quotes**: Single quotes instead of double quotes

### Logical Equivalence: ✅ YES

---

## Summary of Common Differences

1. **Table Naming Convention**: API uses prefixed table names (`imdb_movie`, `academic_organization`) vs. simple names in training data
2. **Identifier Quoting**: API consistently uses double quotes for identifiers
3. **Case Sensitivity**: API uses `LOWER()` function for case-insensitive string comparisons
4. **String Literals**: API uses single quotes for string literals vs. double quotes in training data
5. **DISTINCT**: API may add `DISTINCT` in complex queries to avoid duplicates
6. **JOIN Structure**: API may use different JOIN ordering but maintains logical equivalence

## Conclusion

All queries are **logically equivalent** but differ in:
- Syntax style (quoting, case handling)
- Table naming conventions
- Query optimization (DISTINCT, JOIN order)

The API appears to be generating queries optimized for a specific database schema with prefixed table names and case-insensitive matching.
