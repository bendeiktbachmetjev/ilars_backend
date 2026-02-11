# Doctor Profile Setup

## 1. Run database migration

Execute the migration to create `hospitals` and `doctors` tables:

```bash
psql $DATABASE_URL -f migration_doctors_hospitals.sql
```

Or run the SQL manually in Supabase SQL Editor.

## 2. Add Firebase Service Account to Railway

The backend needs to verify Firebase ID tokens from Google Sign-In.

1. Go to [Firebase Console](https://console.firebase.google.com/) → your project
2. **Project Settings** (gear icon) → **Service accounts**
3. Click **Generate new private key**
4. Save the JSON file
5. In **Railway** → your backend service → **Variables**:
   - Add variable: `FIREBASE_SERVICE_ACCOUNT_JSON`
   - Value: paste the **entire JSON content** (as one line, or multi-line is fine)

## 3. Add more hospitals (optional)

To add hospitals, run in your database:

```sql
INSERT INTO hospitals (name) VALUES ('Your Hospital Name');
```

Hospitals are admin-managed; doctors can only select from this list.

## 4. Google Console

No additional setup needed in Google Cloud Console for this feature. Firebase Authentication with Google Sign-In already provides:

- `uid` – unique user ID
- `email` – from Google account
- `name` – display name (we use for first/last name prefill)
