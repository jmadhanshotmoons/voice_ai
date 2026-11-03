import dotenv from "dotenv";
import path from "path";

dotenv.config({ path: path.resolve(__dirname, "../../../.env") });

// Fail fast with a readable message instead of a Supabase stack trace deep inside a module
const REQUIRED = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"];
const missing = REQUIRED.filter((k) => !process.env[k]);
if (missing.length && process.env.NODE_ENV === "production") {
  console.error(JSON.stringify({ level: "error", event: "missing_env", missing }));
  process.exit(1);
}
