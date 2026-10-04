# Doctor Profile Setup

## 1. Run database migration

Execute the migration to create `hospitals` and `doctors` tables:

```bash
psql $DATABASE_URL -f migration_doctors_hospitals.sql
```

Or run the SQL manually in Supabase SQL Editor.

## 2. Firebase token verification (Railway variables)

The backend verifies every Firebase ID token from Google Sign-In (signature, project, expiry) and
rejects anything else with 401. This needs no secret: by default it uses the public project id
`ilars-659bc` (override with `FIREBASE_PROJECT_ID`).

A service account is optional (only needed if the backend later calls other Firebase Admin APIs):

1. Go to [Firebase Console](https://console.firebase.google.com/) → your project
2. **Project Settings** (gear icon) → **Service accounts**
3. Click **Generate new private key**
4. Save the JSON file
5. In **Railway** → your backend service → **Variables**:
   - Add variable: `FIREBASE_SERVICE_ACCOUNT_JSON`
   - Value: paste the **entire JSON content** (as one line, or multi-line is fine)

Never set `ALLOW_UNVERIFIED_TOKENS=1` in production: it accepts tokens without checking them
(local development only).

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
