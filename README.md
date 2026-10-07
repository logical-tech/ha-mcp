# HA-MCP

MCP server per Home Assistant, installabile come app (add-on) di HA. Un solo file: `ha_mcp/server.py`.

| Tool | Cosa fa |
|---|---|
| `ha_states` | lista compatta entità (filtro per dominio / testo) |
| `ha_rest` | qualsiasi chiamata REST: servizi, stati, template, history, CRUD automazioni/script/scene |
| `ha_ws` | qualsiasi comando WebSocket: registri entità/dispositivi/aree, dashboard, config entries, supervisor |

## Installazione come app su HA

1. **Impostazioni → App → Store → ⋮ → Repository** → aggiungi `https://github.com/logical-tech/ha-mcp`.
2. Ricarica lo Store → "HA MCP" → Installa.
3. Configurazione → `secret`: una stringa casuale di almeno 32 caratteri:
   ```bash
   python3 -c "import secrets;print(secrets.token_urlsafe(32))"
   ```
4. Avvia. Il server ascolta sulla porta `8099`. Il token per parlare con HA lo fornisce la Supervisor in automatico.

## Esposizione con Cloudflare Tunnel

Aggiungi un hostname pubblico al tunnel, es. `mcp.example.com` → `http://<IP-LAN-di-HA>:8099`.
- Tunnel gestito dalla dashboard Cloudflare: **Zero Trust → Networks → Tunnels → Public hostnames → Add**.
- App Cloudflared di HA: aggiungilo in `additional_hosts`.

URL dell'MCP: `https://mcp.example.com/<secret>`

## Collegare Claude

- **claude.ai** (web, app mobile, desktop): Impostazioni → Connettori → Aggiungi connettore personalizzato → incolla l'URL.
- **Claude Code**:
  ```bash
  claude mcp add -s user -t http home-assistant https://mcp.example.com/<secret>
  ```

⚠️ Il secret è la password: chi ha l'URL controlla casa. Non committarlo e non condividerlo.

## Uso locale (senza app)

```bash
HA_URL=https://ha.example.com HA_TOKEN=<long-lived-token> uv run --script ha_mcp/server.py
```
Senza `MCP_SECRET` parla stdio; con `MCP_SECRET` serve HTTP sulla `8099`.
