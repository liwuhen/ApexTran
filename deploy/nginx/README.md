# Nginx Deployment

This Nginx config exposes the frontend and backend under one origin:

```text
browser -> Nginx :80
  /                  -> Next.js frontend 127.0.0.1:3000
  /api/langgraph/*   -> ApexTran WebChannel 127.0.0.1:8000
  /api/models        -> ApexTran WebChannel 127.0.0.1:8000
  /api/skills        -> ApexTran WebChannel 127.0.0.1:8000
```

The one-command local/server startup path is:

```bash
APEXTRAN_PUBLIC_BASE_URL=https://your-domain.example \
BETTER_AUTH_BASE_URL=https://your-domain.example \
scripts/start_nginx_stack.sh start
```

Useful follow-up commands:

```bash
scripts/start_nginx_stack.sh status
scripts/start_nginx_stack.sh logs
scripts/start_nginx_stack.sh stop
```

The script starts the backend WebChannel, starts the frontend server, installs
`deploy/nginx/apextran.conf`, validates it with `nginx -t`, and reloads Nginx.
Set `APEXTRAN_SKIP_NGINX=1` to start only the upstream services.
Use `scripts/start_nginx_stack.sh foreground` in managed terminals that clean up
background child processes when the startup command exits.

In production mode (`APEXTRAN_FRONTEND_MODE=prod`), the script requires Nginx to
be installed unless `APEXTRAN_SKIP_NGINX=1` is set explicitly.

Start the backend WebChannel:

```bash
ApexTran_WEB_HOST=127.0.0.1 ApexTran_WEB_PORT=8000 uv run ApexTran web
```

Start the frontend production server:

```bash
cd frontend
BETTER_AUTH_SECRET=<at-least-32-chars> \
BETTER_AUTH_BASE_URL=https://your-domain.example \
corepack pnpm build

BETTER_AUTH_SECRET=<at-least-32-chars> \
BETTER_AUTH_BASE_URL=https://your-domain.example \
corepack pnpm start --hostname 127.0.0.1 --port 3000
```

Install and reload Nginx:

```bash
sudo cp deploy/nginx/apextran.conf /etc/nginx/conf.d/apextran.conf
sudo nginx -t
sudo systemctl reload nginx
```

For TLS, terminate HTTPS at Nginx and keep the upstream services bound to
`127.0.0.1`. The `/api/langgraph/` location disables buffering and gzip because
that path carries SSE streaming responses.
