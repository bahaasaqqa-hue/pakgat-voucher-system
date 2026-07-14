# Upgrade to v4.0

1. Copy the release files over the repository root while on `develop`.
2. Run:

```powershell
git add .
git commit -m "Add Salla OAuth and multi-merchant voucher automation"
git push
```

3. Merge `develop` into `main` and let Render deploy.
4. Add/verify the OAuth variables in Render.
5. In the Salla app, register this redirect URI exactly:

```text
https://pakgat-voucher-system.onrender.com/oauth/salla/callback
```

6. Log in to `/admin/integrations` and connect the store.
7. Configure its product IDs and merchant redemption code under `/admin/merchants`.

Important: keep `ADMIN_SECRET` stable after merchants are connected. Changing it makes stored OAuth tokens unreadable.
