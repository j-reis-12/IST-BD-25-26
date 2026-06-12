# Databases

> The course introduces students to database design and analysis. The focus is on the relational
> model, covering the logical design of databases (schema design) and implementation, and transaction
> processing systems. Aspects of unstructured and semi-structured data management, decision support
> and data mining systems will also be covered. The objective of this course is to expose the student
> to the basic concepts involved in designing and building an information system, and to practical
> information systems applications design through a team-based project.

## Project 1 - Entity‑Relationship Model and Relational Schema

### Goal
Design a complete and consistent Entity–Relationship model for a zoo information system,
capturing animals, enclosures, compatibility rules, ticketing, billing, and staff allocation.
Convert the conceptual model into a fully normalized relational schema (BCNF/3NF),
complemented with integrity constraints that formalize domain rules not expressible
graphically.

## Project 2 - Database Implementation

### Goal
Implement the “Zoo” database in PostgreSQL with full integrity enforcement through triggers
and ACID‑compliant transactions. Develop a secure RESTful API in Flask for ticket sales, zone
access, and voting, ensuring SQL injection prevention and correct transactional behavior.
Build analytical components using materialized views, OLAP‑style queries, and optimized
indexes to support revenue analysis, zone performance, and visitor behavior insights.
