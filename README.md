# StagDB Community Edition

**Instant Database Branching for Development Teams**

StagDB Community Edition provides instant database branching capabilities by combining Docker containers with ZFS snapshots. Create isolated development databases and instantly branch data states for testing different scenarios - all with zero-copy efficiency.

🌐 **Learn more at [stagdb.com](https://stagdb.com/)**

## What is StagDB?

StagDB revolutionizes database development workflows by enabling developers to:

- **Branch databases instantly** - Create database branches as quickly as Git branches
- **Test with confidence** - Isolate development and testing environments completely
- **Save storage space** - Zero-copy branching means minimal disk usage
- **Work faster** - No more waiting for database dumps or restores

## Key Features

### 🚀 Instant Database Branching
Create database branches in seconds, not minutes. Each branch is a complete, isolated copy of your data that shares storage efficiently through ZFS snapshots.

### 🐳 Docker Integration
PostgreSQL databases run in Docker containers with ZFS-backed storage, providing both isolation and portability.

### 🖥️ Web Dashboard
Intuitive web interface for managing hosts, databases, and branches. Connect to remote VMs or use local Docker environments.

### 📦 Zero-Copy Technology
Leverages ZFS copy-on-write snapshots to create database branches without duplicating data until changes are made.

### 🔒 Secure SSH Management
Connect to remote hosts securely via SSH for distributed database management across your infrastructure.

## Use Cases

### Development Teams
- **Feature Development**: Create a database branch for each feature, test independently
- **Bug Investigation**: Branch from production data to investigate issues safely
- **Code Reviews**: Share database states along with code changes

### QA & Testing
- **Test Data Management**: Maintain consistent test datasets across different test runs
- **Regression Testing**: Quickly reset database state between test suites
- **Performance Testing**: Test with production-like data without affecting production

### Data Analysis
- **Experimentation**: Try different data transformations without affecting source data
- **Reporting**: Create stable snapshots for consistent reporting periods
- **Data Science**: Branch datasets for different modeling experiments

## Quick Start

### Prerequisites
- Linux host with ZFS support
- Docker and Docker Compose
- SSH access (for remote hosts)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd stagdb-ce
   ```

2. **Start with Docker Compose**
   ```bash
   docker compose up --build
   ```

3. **Access the dashboard**
   - Open http://localhost in your browser
   - Login with default credentials: `admin` / `stagdb123`

4. **Setup your first host**
   - Use the Docker host setup for local development
   - Or connect to a remote VM with ZFS and Docker

### First Database

1. **Configure storage** - Set up ZFS pools for database storage
2. **Create database** - Launch a PostgreSQL container with ZFS backing
3. **Create branches** - Instantly branch your database for different scenarios
4. **Connect and develop** - Use standard PostgreSQL tools and connection strings

## Technology Stack

- **Backend**: Django 4.2.9 with Django REST Framework
- **Database**: SQLite3 (for app data), PostgreSQL containers (managed databases)
- **Storage**: ZFS for zero-copy snapshots and clones
- **Containers**: Docker for database isolation
- **Frontend**: HTML/CSS/JavaScript dashboard
- **Infrastructure**: SSH for remote host management

## Architecture

StagDB CE uses a three-layer architecture:

1. **Management Layer**: Django web application for orchestration
2. **Container Layer**: Docker containers running PostgreSQL instances
3. **Storage Layer**: ZFS datasets providing snapshot and clone capabilities

Each database runs in its own Docker container with a dedicated ZFS dataset. Branches are created by taking ZFS snapshots and creating clones, enabling instant database duplication with minimal storage overhead.

## Documentation

- **Setup Guide**: See [CLAUDE.md](CLAUDE.md) for detailed development instructions
- **API Reference**: RESTful API for programmatic database management
- **Storage Configuration**: Multiple storage backend options supported
- **Docker Integration**: Container lifecycle management and monitoring

## Support & Community

- **Website**: [stagdb.com](https://stagdb.com/)
- **Issues**: Report bugs and request features via GitHub Issues
- **Community**: Join discussions about database branching and development workflows

## License

StagDB Community Edition is open source software. Check the LICENSE file for details.

---

**Ready to revolutionize your database workflow?** Start with StagDB Community Edition and experience the power of instant database branching. Visit [stagdb.com](https://stagdb.com/) to learn more about our enterprise solutions.
