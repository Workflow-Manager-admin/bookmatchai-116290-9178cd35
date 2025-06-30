# Supabase Integration for BookSwap+

## Database Configuration

BookSwap+ uses Supabase as the PostgreSQL database backend. The database connection is already configured in the backend application.

### Database Connection Details
- **URL**: https://uujtmzkpxvpkhpprtjjv.supabase.co
- **Database URL**: postgresql://postgres:ClashRoyale@db.uujtmzkpxvpkhpprtjjv.supabase.co:5432/postgres
- **Anon Key**: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV1anRtemtweHZwa2hwcHJ0amp2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEwMzA1MTYsImV4cCI6MjA2NjYwNjUxNn0.-0Ac5LEt1_bX4rnbL2jUoZGHTA4GsYacijQ_nwFVyjo

## Database Schema

The following tables are created by SQLAlchemy models:

### Users Table
- Stores user profile information
- Links with Clerk.dev authentication via `clerk_user_id`
- Supports user preferences and notification settings

### Books Table  
- Book listings for swap/giveaway
- Includes detailed book metadata
- Links to owner (User)
- Supports semantic matching through embedding field

### Swap Offers Table
- Manages swap requests between users
- Tracks offer status and history
- Links requester, recipient, and requested book

### Notifications Table
- User notification system
- Supports different notification types
- Tracks read status and delivery preferences

## Required Supabase Configuration

### 1. Database Setup
The database tables are automatically created by the FastAPI application on startup using SQLAlchemy migrations.

### 2. Row Level Security (optional)
While the application handles authentication through Clerk and SQLAlchemy ORM, you may want to configure RLS policies for additional security:

```sql
-- Enable RLS on tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE books ENABLE ROW LEVEL SECURITY;
ALTER TABLE swap_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- Example policies (customize based on requirements)
CREATE POLICY "Users can view their own profile" ON users
  FOR SELECT USING (clerk_user_id = auth.jwt() ->> 'sub');

CREATE POLICY "Users can update their own profile" ON users  
  FOR UPDATE USING (clerk_user_id = auth.jwt() ->> 'sub');
```

### 3. Database Functions (optional)
You may want to add database functions for advanced features:

```sql
-- Function for semantic search (requires pgvector extension)
CREATE OR REPLACE FUNCTION search_books_by_embedding(query_embedding vector, similarity_threshold float DEFAULT 0.7)
RETURNS TABLE(book_id integer, similarity float) AS $$
BEGIN
  RETURN QUERY
  SELECT id, 1 - (semantic_embedding <=> query_embedding) as similarity
  FROM books 
  WHERE 1 - (semantic_embedding <=> query_embedding) > similarity_threshold
  ORDER BY semantic_embedding <=> query_embedding;
END;
$$ LANGUAGE plpgsql;
```

### 4. Environment Variables
Ensure these environment variables are set in your deployment:

```
SUPABASE_URL=https://uujtmzkpxvpkhpprtjjv.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV1anRtemtweHZwa2hwcHJ0amp2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTEwMzA1MTYsImV4cCI6MjA2NjYwNjUxNn0.-0Ac5LEt1_bX4rnbL2jUoZGHTA4GsYacijQ_nwFVyjo
SUPABASE_DB_URL=postgresql://postgres:ClashRoyale@db.uujtmzkpxvpkhpprtjjv.supabase.co:5432/postgres
```

## Integration Notes

1. **Authentication**: The application uses Clerk.dev for authentication, not Supabase Auth
2. **Database Access**: Direct PostgreSQL connection via SQLAlchemy ORM
3. **Real-time Features**: If needed, can be implemented using Supabase Realtime subscriptions
4. **File Storage**: For future file uploads (book covers, etc.), use Supabase Storage

## Next Steps

1. Configure Clerk.dev webhook endpoints to sync user data
2. Set up any required database indexes for performance
3. Configure backup and monitoring in Supabase dashboard
4. Add any custom database functions for advanced matching algorithms
