# StagDB Community Edition

<div align="center">

**Instant Database Branching for Development Teams**

Branch your databases as easily as you branch your code.

[Website](https://stagdb.com/) • [Documentation](#documentation) • [Quick Start](#quick-start) • [Community](#support--community)

</div>

---

## The Problem

Modern development teams face a common challenge: managing database state across multiple features, bug fixes, and testing scenarios. Traditional approaches are slow and cumbersome:

- **Database dumps take forever** - Waiting 10+ minutes to restore a production snapshot
- **Testing is risky** - Running migrations or data transformations without a safety net
- **Isolation is hard** - Multiple developers sharing a single development database
- **Storage is expensive** - Full database copies consume massive disk space

## The Solution

StagDB Community Edition combines Docker containers with ZFS snapshots to provide **instant database branching**. Create isolated development databases and branch data states in seconds - all with zero-copy efficiency.

Think of it as **Git for your databases**.

---

## Why StagDB?

### ⚡ Instant Branching
Create database branches in **under 10 seconds**, not minutes. Each branch is a complete, isolated copy that shares storage efficiently through ZFS copy-on-write technology.

### 💾 Zero-Copy Efficiency
ZFS snapshots mean branches only store the differences from their source. A 100GB database might only consume 1GB when branched, growing only as data changes.

### 🔒 Complete Isolation
Every database runs in its own Docker container with dedicated resources. Test destructive operations, run parallel tests, or experiment freely without affecting other environments.

### 🎯 Simple to Use
Web-based dashboard for the entire database lifecycle. No complex CLI commands or ZFS expertise required - though power users have full access to advanced features.

### 🚀 Production-Ready
Enterprise-grade security, comprehensive audit trails, dependency protection, and multi-layered error handling. Built for teams that need reliability.

---

## Key Features

### 🐳 Advanced Docker Integration
- **Multi-Version PostgreSQL Support** - Versions 11, 12, 13, 14, 15, and 16
- **Intelligent Port Management** - Automatic allocation with conflict detection (5432-5500 range)
- **Container Health Monitoring** - Real-time status tracking and health checks
- **Image Pre-pulling** - Optimized deployments with automatic image management

### 🗄️ Flexible Database Creation
- **Empty Databases** - Fresh PostgreSQL instances for new projects
- **Clone from Existing** - Instant copy of any database with full data and schema
- **Restore from Snapshot** - Time-travel to any previous database state

### 📊 Complete Lineage Tracking
- **Audit Trail** - Full history of all ZFS operations (create, snapshot, clone, destroy)
- **Dependency Protection** - Prevents deletion of source databases with active clones
- **Visual Genealogy** - See the complete family tree of database relationships

### ⚙️ Intelligent Storage Configuration
Guided setup wizard with smart recommendations based on your system:
- **Existing ZFS Pool** - Use your current ZFS infrastructure
- **Dedicated Disks** - Create new pools with RAID-Z1/Z2/Z3 configurations
- **Image Files** - Quick setup with sparse or pre-allocated files
- **Directory Storage** - Development mode without ZFS (limited features)
- **Hybrid Storage** - SSD cache + HDD data pools for optimal performance

### 🖥️ Production-Ready Web Dashboard
- Database creation wizard with advanced options
- Real-time monitoring and health status
- One-click connection information with copy-to-clipboard
- ZFS operation history and storage metrics
- Comprehensive host management and validation

### 🔐 Enterprise-Grade Security
- **Secure Password Generation** - 32-character alphanumeric passwords (shell-safe)
- **SSH Key Management** - Secure remote host connections
- **Multi-layered Error Handling** - Comprehensive recovery mechanisms
- **Resource Cleanup** - Automatic cleanup with dependency tracking

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

## Use Cases

### For Development Teams

**Feature Development**
```
main-db (production data)
  ├── feature-auth (Alice's branch)
  ├── feature-payments (Bob's branch)
  └── bugfix-login (Carol's branch)
```
Each developer works with isolated, production-like data without conflicts.

**Bug Investigation**
1. Clone production database
2. Reproduce the bug safely
3. Test fix on cloned data
4. Deploy with confidence

**Code Reviews**
Share database states alongside code changes:
- Reviewers can test with exact data conditions
- No "works on my machine" surprises

### For QA & Testing

**Test Data Management**
```bash
# Create baseline test database
golden-master-db

# Clone for each test suite
├── integration-tests
├── e2e-tests
└── performance-tests
```
Consistent starting point for every test run.

**Regression Testing**
- Take snapshot before each test
- Reset database in 5 seconds between runs
- No slow teardown/setup cycles

**Performance Testing**
- Test with production-scale data
- Branch and benchmark safely
- Compare performance across branches

### For Data Analysis

**Experimentation**
- Try different data transformations
- Test ETL pipelines
- No risk to source data

**Reporting**
- Snapshot at reporting period end
- Consistent data for recurring reports
- Historical snapshots for trend analysis

**Data Science**
- Branch datasets for different models
- Compare results across experiments
- Reproducible analysis with snapshotted data

---

## Architecture

StagDB uses a three-layer architecture:

```
┌─────────────────────────────────────────┐
│      Management Layer (Django)          │
│  - Web Dashboard                        │
│  - REST API                             │
│  - Orchestration Logic                  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│      Container Layer (Docker)           │
│  ┌──────────┐  ┌──────────┐            │
│  │ PostgreSQL│  │ PostgreSQL│  ...       │
│  │ v15 :5432│  │ v16 :5433│            │
│  └─────┬────┘  └─────┬────┘            │
└────────┼─────────────┼─────────────────┘
         │             │
┌────────▼─────────────▼─────────────────┐
│      Storage Layer (ZFS)                │
│  pool/stagdb/databases/                 │
│    ├── db1/          ← Dataset          │
│    │   └── @snap1    ← Snapshot         │
│    ├── db2/          ← Clone of db1     │
│    └── db3/          ← Independent DB   │
└─────────────────────────────────────────┘
```

### How It Works

**Database Creation (Empty)**
1. Allocate available port (5432-5500)
2. Create ZFS dataset: `pool/stagdb/databases/dbname`
3. Generate secure 32-character password
4. Launch PostgreSQL container with dataset mounted
5. Wait for PostgreSQL initialization
6. Record operation in audit trail

**Database Cloning**
1. Take ZFS snapshot of source: `sourcedb@clone-timestamp`
2. Create ZFS clone: `newdb` (instant, zero-copy)
3. Launch container with cloned dataset
4. Reuse source database password (ZFS copied auth files)
5. Record clone relationship and lineage

**Storage Efficiency**
- Clones share unchanged data blocks with source
- Only modified blocks consume additional space
- 10 clones of a 50GB database might use 55GB total

---

## Technology Stack

- **Backend**: Django 4.2.25 with Django REST Framework 3.16.1
- **Database**: SQLite3 (for StagDB metadata), PostgreSQL 11-16 (managed databases)
- **Storage**: ZFS for copy-on-write snapshots and clones
- **Containers**: Docker for database isolation and portability
- **Frontend**: HTML/CSS/JavaScript dashboard (no build step required)
- **Infrastructure**: SSH/Paramiko for remote host management

---

## API Reference

StagDB provides a comprehensive REST API for programmatic database management.

### Authentication

All API endpoints require authentication via Django session cookies.

```bash
# Login first
curl -X POST http://localhost/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "stagdb123"}'
```

### Database Endpoints

**Create Database**
```bash
POST /api/databases/create/
Content-Type: application/json

{
  "name": "my-database",
  "host_id": 1,
  "db_version": "15",
  "creation_type": "empty",  // or "clone" or "snapshot"
  "source_database_id": 2,   // required for "clone"
  "source_snapshot": "pool/stagdb/databases/source@snapshot-name",  // required for "snapshot"
  "description": "Feature development database"
}
```

**List Databases**
```bash
GET /api/databases/list/
```

**Get Database Details**
```bash
GET /api/databases/{id}/
```

**Start/Stop/Restart Database**
```bash
POST /api/databases/{id}/start/
POST /api/databases/{id}/stop/
POST /api/databases/{id}/restart/
```

**Get Connection Information**
```bash
GET /api/databases/{id}/connection/
```

**Delete Database**
```bash
DELETE /api/databases/{id}/delete/
```

**List Snapshots**
```bash
GET /api/databases/snapshots/
GET /api/databases/{id}/snapshots/
```

**Check Dependencies**
```bash
GET /api/databases/{id}/dependencies/
```

### Response Format

All successful responses follow this format:

```json
{
  "success": true,
  "database": {
    "id": 3,
    "name": "my-database",
    "version": "15",
    "status": "running",
    "health": "healthy",
    "host": {
      "id": 1,
      "name": "docker-host"
    },
    "creation_type": "empty",
    "storage_used_mb": 245,
    "connection_info": {
      "host": "localhost",
      "port": 5433,
      "database": "my-database",
      "username": "postgres",
      "password": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
      "connection_string": "postgresql://postgres:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6@localhost:5433/my-database"
    },
    "created_at": "2025-12-05T10:30:00Z"
  }
}
```

Error responses:

```json
{
  "success": false,
  "message": "No available ports in range 5432-5500"
}
```

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
