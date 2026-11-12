/*
 * Public configuration. These two values are safe to ship to the browser:
 * the anon/publishable key can only call the RPC functions granted in the
 * database and every table has Row Level Security enabled with no policies,
 * so direct table access is impossible.
 */
window.SCHOOL_CONFIG = {
  supabaseUrl: "https://nojpjuowrhinkxpzumum.supabase.co",
  supabaseKey:
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5vanBqdW93cmhpbmt4cHp1bXVtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ0ODgzMTAsImV4cCI6MjExMDA2NDMxMH0.fxnaYZs0wu85cpcczz8DMJ57SKqKUBV37wjS-3VpSPk",
  // Face descriptors are compared against this Euclidean distance.
  faceThreshold: 0.5,
};
