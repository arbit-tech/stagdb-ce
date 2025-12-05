# StagDB Community Edition

<div align="center">

**Instant Database Branching for Development Teams**

Branch your databases as easily as you branch your code.

[Website](https://stagdb.com/) • [Documentation](#documentation) • [Quick Start](#quick-start) • [Community](#support--community)

</div>

---

## The Problem

Modern development teams struggle with managing database state across features, bug fixes, and testing. Traditional approaches waste time with slow database dumps, risk production data during testing, and consume massive storage with full copies.

StagDB solves this with **instant database branching** using Docker and ZFS snapshots. Create isolated databases in seconds with zero-copy efficiency. Think of it as **Git for your databases**.

---

## Key Features

- **⚡ Instant Branching** - Create database branches in under 10 seconds using ZFS copy-on-write technology
- **💾 Zero-Copy Efficiency** - Branches only store differences; a 100GB database might use just 1GB when cloned
- **🔒 Complete Isolation** - Each database runs in its own Docker container with dedicated resources
- **🐳 Multi-Version PostgreSQL** - Support for PostgreSQL versions 11, 12, 13, 14, 15, and 16
- **🗄️ Flexible Creation** - Empty databases, clone existing, or restore from snapshots
- **📊 Lineage Tracking** - Full audit trail with dependency protection and visual genealogy
- **⚙️ Smart Storage** - Guided setup with recommendations for ZFS pools, RAID configs, and image files
- **🖥️ Web Dashboard** - Complete lifecycle management with real-time monitoring and health status
- **🔐 Enterprise Security** - Secure password generation, SSH key management, and comprehensive error handling

---

## Quick Start

### Prerequisites

Before you begin, ensure you have:

- **Linux host with ZFS support** - Ubuntu 20.04+, Debian 11+, or any Linux with ZFS modules
- **Docker and Docker Compose** - Version 20.10+ recommended
- **Minimum 4GB RAM** - 8GB+ recommended for production use
- **SSH access** (optional) - Only needed for remote host management

> **Note:** ZFS is available on most Linux distributions. On Ubuntu/Debian: `apt install zfsutils-linux`

### Installation

**1. Clone the repository**

```bash
git clone https://github.com/arbit-tech/stagdb-ce.git
cd stagdb-ce
```

**2. Configure environment variables (optional)**

```bash
cp .env.example .env
# Edit .env if you want to customize settings
# Defaults work fine for local development
```

Default credentials:
- Username: `admin`
- Password: `stagdb123`

**3. Start StagDB**

```bash
docker compose up --build
```

This will:
- Build the StagDB container
- Run database migrations
- Create the admin user
- Start the web server on port 80

**4. Access the dashboard**

Open your browser:
- **Local setup**: http://localhost
- **Remote server**: http://YOUR_SERVER_IP
- Login with default credentials

**5. Configure your first host**

Click **"🐳 Setup Docker Host"** and follow the guided wizard:

1. **System Validation** - StagDB checks for Docker and ZFS
2. **Storage Recommendations** - Get intelligent suggestions based on your system
3. **Storage Configuration** - Choose and configure your storage backend
4. **Verification** - Confirm everything is working

> **Tip:** For local development, choose "Use Existing ZFS Pool" if you have one, or "Image File" for quick setup without dedicating disks.

---

## Creating Your First Database

Once your host is configured:

### 1. Navigate to Dashboard
Click **"+ Create Database"** from the main dashboard.

### 2. Choose Creation Type

**Empty Database** - Start fresh
- Best for: New projects, testing schemas
- Time: ~8 seconds
- Storage: Minimal (PostgreSQL base install)

**Clone from Database** - Copy an existing database
- Best for: Feature development, bug investigation
- Time: ~5 seconds (instant ZFS clone)
- Storage: Only stores changes from source (copy-on-write)

**Restore from Snapshot** - Time travel to a previous state
- Best for: Regression testing, data recovery
- Time: ~5 seconds
- Storage: Only stores changes from snapshot

### 3. Configure Options

- **Name**: Alphanumeric with underscores (e.g., `feature_auth_refactor`)
- **PostgreSQL Version**: Choose from 11-16
- **Description**: Optional notes about this database's purpose
- **Source**: Select source database or snapshot (for clone/restore types)

### 4. Monitor Creation

Watch real-time progress:
- ZFS dataset creation
- Docker container launch
- PostgreSQL initialization
- Health check validation

### 5. Connect and Develop

Get connection details with one click:

```bash
Host: localhost
Port: 5433
Database: feature_auth_refactor
Username: postgres
Password: [auto-generated 32-char password]

# Connection string (copy-paste ready)
postgresql://postgres:password@localhost:5433/feature_auth_refactor
```

---

## Architecture

StagDB uses a three-layer architecture: Django manages orchestration, Docker provides container isolation, and ZFS enables zero-copy snapshots. Each database runs in its own PostgreSQL container backed by a dedicated ZFS dataset, allowing instant cloning through ZFS snapshot and clone operations.

**Technology Stack**: Django 4.2.25, PostgreSQL 11-16, ZFS, Docker, SSH/Paramiko

---

## Configuration

### Environment Variables

StagDB is configured via environment variables in `.env`:

```bash
# Django Settings
SECRET_KEY=django-insecure-change-this-in-production
DEBUG=True
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@stagdb.local
DJANGO_SUPERUSER_PASSWORD=stagdb123
```

### Docker Compose Configuration

The default `docker-compose.yml` is configured for local development:

```yaml
services:
  stagdb:
    build: .
    ports:
      - "80:8000"  # Change to "8080:8000" for custom port
    volumes:
      - .:/app
      - /var/run/docker.sock:/var/run/docker.sock
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
    privileged: true  # Required for nsenter (ZFS commands)
    pid: host         # Required for host namespace access
```

### Storage Configuration

Configure storage through the web dashboard or directly in the database:

- **Existing Pool**: Use an existing ZFS pool
- **Dedicated Disk**: Format a disk and create a new pool
- **Image File**: Create a pool from a file (great for development)
- **Directory**: Bypass ZFS (limited features, dev only)

---

## Advanced Topics

### Docker Host Mode vs Remote VM

**Docker Host Mode** (Recommended for single-server setup)
- Runs database containers on the same host as StagDB
- Uses `nsenter` to execute ZFS commands in host namespace
- No SSH configuration required
- IP: 172.17.0.1 (Docker bridge network)

**Remote VM Mode** (For distributed architectures)
- Runs database containers on remote hosts via SSH
- Requires SSH key or password authentication
- Supports multiple remote hosts
- Full paramiko-based remote execution

### ZFS Dataset Hierarchy

```
pool/
└── stagdb/
    ├── databases/           # All database datasets live here
    │   ├── prod-db/        # Production data
    │   │   ├── @daily-2025-12-05
    │   │   └── @daily-2025-12-04
    │   ├── feature-auth/   # Clone of prod-db@daily-2025-12-05
    │   └── test-db/        # Independent database
    └── [future: backups/, logs/, etc.]
```

### Password Handling for Clones

**Important:** When cloning a database, the source password is automatically reused.

Why? ZFS clones copy the entire PostgreSQL data directory, including:
- `pg_hba.conf` (authentication config)
- Password hashes in system tables
- All user accounts and permissions

PostgreSQL ignores the `POSTGRES_PASSWORD` environment variable when the data directory already exists. Setting a different password would cause authentication failures.

### Port Allocation Strategy

- **Range**: 5432-5500 (69 available ports)
- **Algorithm**: Linear search for first available port
- **Collision Detection**: Checks existing Database records
- **Exhaustion**: Returns error if all ports in use (raise the limit by editing `database_manager.py`)

### Performance Considerations

**Database Creation Times**
- Empty database: 5-10 seconds
- Clone from database: 3-7 seconds (instant ZFS clone + container start)
- Restore from snapshot: 3-7 seconds

**Storage Overhead**
- Empty PostgreSQL database: ~35MB
- Cloned database (no changes): ~1MB
- Snapshots: Negligible (metadata only)

**Scalability Limits**
- Max databases per host: 69 (limited by port range)
- Max storage: Limited by ZFS pool capacity
- Recommended: <20 active databases per host for optimal performance

---

## Troubleshooting

### Common Issues

**"Host validation failed: ZFS not found"**
```bash
# Install ZFS on Ubuntu/Debian
sudo apt update
sudo apt install zfsutils-linux

# Verify installation
zfs version
```

**"No available ports in range 5432-5500"**
- Stop unused databases to free ports
- Or edit `core/database_manager.py` to increase PORT_RANGE_END

**"Permission denied accessing Docker socket"**
- Ensure StagDB container runs in privileged mode
- Check docker-compose.yml has `privileged: true`

**"Database container won't start"**
- Check logs: `docker logs stagdb_db_yourdbname`
- Verify ZFS dataset exists: `zfs list | grep stagdb`
- Ensure PostgreSQL image is pulled: `docker images | grep postgres`

**"Clone failed: source database not found"**
- Verify source database exists and is active
- Check source database is on the same host (cross-host cloning not yet supported)

### Debug Mode

Enable verbose logging:

```bash
# Edit docker-compose.yml
environment:
  - DEBUG=True

# Restart StagDB
docker compose restart
```

View logs:
```bash
docker compose logs -f stagdb
```

### Getting Help

- **Documentation**: Full guides at stagdb.com/docs (coming soon)
- **GitHub Issues**: Report bugs or request features
- **Community**: Join discussions about database workflows

---

## Roadmap

### Currently Available
- ✅ PostgreSQL versions 11-16
- ✅ Docker host and remote VM support
- ✅ ZFS snapshot and clone operations
- ✅ Web dashboard with full CRUD
- ✅ REST API for automation
- ✅ Intelligent storage configuration
- ✅ Database lineage tracking
- ✅ Dependency protection

### Coming Soon
- 🔄 Cross-host cloning (clone databases between different hosts)
- 🔄 Scheduled snapshots (automatic daily/weekly snapshots)
- 🔄 MySQL/MariaDB support
- 🔄 Role-based access control (multi-user with permissions)
- 🔄 Webhook integrations (notify Slack/Discord on events)
- 🔄 CLI tool (manage databases from terminal)

### Future Considerations
- 📋 MongoDB support
- 📋 Backup to S3/cloud storage
- 📋 Migration tool (import from other systems)
- 📋 Metrics and monitoring dashboard
- 📋 Database diff tool (compare schemas)

---

## Contributing

We welcome contributions! Whether you're fixing bugs, adding features, or improving documentation.

### Ways to Contribute

- 🐛 **Report bugs** via GitHub Issues
- 💡 **Suggest features** you'd like to see
- 📖 **Improve documentation** (README, comments, guides)
- 🔧 **Submit pull requests** with fixes or features
- ⭐ **Star the repo** if you find it useful

### Development Setup

```bash
# Clone repository
git clone https://github.com/arbit-tech/stagdb-ce.git
cd stagdb-ce

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py create_superuser

# Start development server
python manage.py runserver 0.0.0.0:8000
```

See [CLAUDE.md](./CLAUDE.md) for detailed architecture documentation and development guidelines.

---

## Support & Community

- **Website**: [stagdb.com](https://stagdb.com/)
- **Documentation**: stagdb.com/docs (coming soon)
- **GitHub Issues**: Report bugs and request features
- **Discussions**: Share your use cases and workflows
- **Email**: hello@stagdb.com

---

## License

StagDB Community Edition is open source software released under the [MIT License](./LICENSE).

---

## Acknowledgments

Built with:
- [Django](https://www.djangoproject.com/) - Web framework
- [Docker](https://www.docker.com/) - Container platform
- [ZFS](https://openzfs.org/) - Storage platform
- [PostgreSQL](https://www.postgresql.org/) - Database engine

Inspired by the development workflows of modern software teams who deserve better database tooling.

---

<div align="center">

**Ready to revolutionize your database workflow?**

[Get Started](#quick-start) • [View Documentation](#documentation) • [Join Community](#support--community)

Built with ❤️ by the StagDB team

</div>
