# Changelog

## Unreleased

### Changed
- Renamed host mapping `lightsiddious.arkham.asylum` to `nightmaresiddious.arkham.asylum` in DNS/docs.
- Updated Pi-hole DNS defaults to include requested compose `dns` servers (1.1.1.1, 9.9.9.9), enabled DNSSEC, and expanded `FTLCONF_dns_upstreams` default.
- Aligned Pi-hole configuration with documented `FTLCONF_*` variables for password/theme/DNS upstreams (`FTLCONF_webserver_api_password`, `FTLCONF_webserver_interface_theme`, `FTLCONF_dns_upstreams`).
- Added `.gitattributes` to enforce LF endings for Pi-hole list/config files and prevent `Invalid Target ...^M` during gravity updates.
- Replaced Pi-hole adlists with the exact requested set (StevenBlack, RPiList Phishing/Streaming/easylist/spam.mails, anudeepND, Firebog Easyprivacy/Easylist/Prigent-Ads/AdguardDNS).
- Set default Pi-hole web password to `admin123` in `.env` and compose fallback.
- Removed `.env.example` and `example.env` templates; `.env` is now the single directly-used runtime configuration file.
- Refactored `docker-compose.yml` with consistent `container_name` values in lowercase-kebab-case, explicit `hostname` per service and shared `intranet` network.
- Standardized service restart policy to `restart: unless-stopped` across all services.

### Added
- Added Pi-hole web theme configuration (`PIHOLE_WEBTHEME`, default `default-darker` / "Pi-hole Midnight").
- Added `docker/pihole/adlists.list` for direct Pi-hole usage.
- Added a complete `.env` file with production-ready defaults for DNS, Pi-hole, DHCP, MQTT, InfluxDB and Grafana.
- Extended README with a dedicated setup flow for fixed IP distribution via Pi-hole DHCP and DHCP troubleshooting steps.
- Added `docker/pihole/etc-dnsmasq.d/04-static-dhcp.conf` template to define static DHCP leases (`dhcp-host=...`).
- Added optional Pi-hole DHCP environment settings (`PIHOLE_DHCP_*`) for centralized LAN DHCP management.
- Added Pi-hole lighttpd external redirect config so `http://<host>:8088` redirects to `/admin/` instead of returning 403 on root path.
- Added Pi-hole service with persistent volumes and timezone handling.
- Added Pi-hole DNS records file at `docker/pihole/custom.list` for `*.arkham.asylum` host mappings.

### Ports
- Added Pi-hole DNS ports `53/tcp` and `53/udp`.
- Added Pi-hole web UI mapping `8088:80` (collision-safe management UI).
- No existing service ports were changed.
