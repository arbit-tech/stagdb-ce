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

### 🐳 Advanced Docker Integration
- **Multi-Version PostgreSQL Support** - PostgreSQL versions 11, 12, 13, 14, 15, 16
- **Intelligent Port Management** - Automatic allocation with conflict detection (5432-5500 range)
- **Container Health Monitoring** - Real-time status tracking and health checks
- **Image Pre-pulling** - Optimized deployments with automatic image management

### 🗄️ Comprehensive Database Management
- **Multiple Creation Types** - Create empty databases, clone from existing, or restore from snapshots
- **Database Lineage Tracking** - Full audit trail of cloning and snapshot operations
- **Dependency Protection** - Prevents accidental deletion of source databases with active clones
- **Storage Metrics** - Detailed ZFS dataset usage and performance monitoring

### 🖥️ Production-Ready Web Dashboard
Intuitive web interface for complete database lifecycle management:
- Database creation with advanced options
- Real-time monitoring and health status
- Connection information and credential management
- ZFS operation history and lineage visualization

### ⚙️ Intelligent Storage Configuration
Guided setup wizard with smart storage recommendations based on your system resources. Supports multiple storage backends including existing ZFS pools, dedicated disks with RAID configurations, image files, and directory storage.

### 📦 Zero-Copy Technology
Leverages ZFS copy-on-write snapshots to create database branches without duplicating data until changes are made. Advanced features include:
- **Snapshot Hierarchy** - Track the complete lineage from root to current state
- **Orphaned Resource Cleanup** - Automated maintenance and garbage collection
- **Cross-Dataset Operations** - Clone databases across different storage configurations

### 🔒 Enterprise-Grade Security & Reliability
- **Secure Password Generation** - 32-character alphanumeric passwords for maximum compatibility
- **SSH Key Management** - Secure remote host connections
- **Multi-layered Error Handling** - Comprehensive recovery mechanisms
- **Resource Cleanup** - Complete cleanup with dependency tracking

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
   git clone https://github.com/arbit-tech/stagdb-ce.git
   cd stagdb-ce
   ```

2. **Start with Docker Compose**
   ```bash
   docker compose up --build
   ```

3. **Access the dashboard**
   - **Local setup**: Open http://localhost in your browser
   - **Remote server**: Open http://YOUR_SERVER_IP in your browser
   - **Custom port**: If you modified the Docker Compose file, use the appropriate port
   - Login with default credentials: `admin` / `stagdb123`

4. **Setup your first host**
   - Click "🐳 Setup Docker Host" to configure your environment with guided storage setup
   - The setup wizard includes intelligent storage recommendations and advanced ZFS configuration options
   - Or manually connect to a remote VM with ZFS and Docker support

### First Database

1. **Complete host setup** - Storage configuration is now integrated into the Docker host setup wizard
2. **Create database** - Launch a PostgreSQL container with ZFS backing:
   - Choose from PostgreSQL versions 11-16
   - Select creation type: Empty, Clone existing, or Restore from snapshot
   - Add description and configure advanced options
3. **Monitor and manage** - View real-time status, health metrics, and storage usage
4. **Create branches** - Instantly branch your database:
   - Clone from existing databases for feature development
   - Create manual snapshots for testing milestones
   - Restore from any snapshot to previous states
5. **Connect and develop** - Use standard PostgreSQL tools with provided connection details

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

## Production-Ready Database Management

### Comprehensive Database Operations
- **Multi-Type Database Creation**: Create empty databases, clone from existing databases, or restore from ZFS snapshots
- **Advanced PostgreSQL Support**: Full support for PostgreSQL versions 11, 12, 13, 14, 15, and 16 with optimized container configurations
- **Intelligent Resource Management**: Automatic port allocation, container health monitoring, and resource usage tracking
- **Database Lifecycle Management**: Complete start/stop/restart/delete operations with dependency protection

### ZFS Integration & Storage Management
- **Advanced ZFS Operations**: Dataset creation, snapshot management, and clone operations with full audit trails
- **Storage Metrics & Monitoring**: Detailed dataset usage, compression ratios, and performance metrics
- **Lineage Tracking**: Complete database genealogy showing clone relationships and snapshot history
- **Automated Cleanup**: Orphaned snapshot detection and cleanup with dependency-aware resource management

### Enterprise-Grade Features
- **Security**: Cryptographically secure password generation with shell-safe alphanumeric characters
- **Reliability**: Multi-layered error handling, automatic recovery mechanisms, and comprehensive logging
- **Performance**: Sub-10-second database creation, image pre-pulling, and optimized ZFS configurations
- **Scalability**: Support for up to 68 concurrent databases per host with intelligent port management

### Enhanced Storage Configuration
- **Intelligent Recommendations**: System automatically analyzes available resources and suggests optimal storage configurations
- **Advanced ZFS Options**: Support for RAID-Z configurations, compression settings, and deduplication
- **Integrated Workflow**: Storage configuration is now seamlessly integrated into the host setup process
- **Visual Interface**: Rich recommendation cards with pros/cons analysis and difficulty ratings

## API Reference

StagDB CE provides a comprehensive REST API for programmatic database management:

### Database Management Endpoints
- **Database CRUD**: `POST /api/databases/create/`, `GET /api/databases/list/`, `DELETE /api/databases/{id}/delete/`
- **Lifecycle Management**: `POST /api/databases/{id}/start/`, `POST /api/databases/{id}/stop/`, `POST /api/databases/{id}/restart/`
- **Monitoring**: `GET /api/databases/{id}/status/`, `GET /api/databases/{id}/logs/`, `GET /api/databases/{id}/connection/`
- **Advanced Operations**: `GET /api/databases/snapshots/`, `POST /api/databases/cleanup-snapshots/`, `GET /api/databases/{id}/dependencies/`

### Database Creation Options
```json
{
  "name": "my-database",
  "host_id": 1,
  "db_version": "15",
  "creation_type": "empty|clone|snapshot",
  "source_database_id": 2,
  "source_snapshot": "pool/stagdb/databases/source@snapshot-name",
  "description": "Feature development database"
}
```

### Response Format
```json
{
  "success": true,
  "database": {
    "id": 3,
    "name": "my-database",
    "version": "15",
    "status": "running",
    "health": "healthy",
    "connection_info": {
      "host": "localhost",
      "port": 5433,
      "database": "my-database",
      "username": "postgres",
      "password": "secure32charpassword123",
      "connection_string": "postgresql://postgres:password@localhost:5433/my-database"
    }
  }
}
```

## Documentation

- **Setup Guide**: See [CLAUDE.md](CLAUDE.md) for detailed development instructions and architecture overview
- **Database Management**: Complete PostgreSQL lifecycle management with ZFS-backed instant branching
- **Storage Configuration**: Comprehensive wizard with intelligent recommendations for ZFS pools, RAID configurations, and storage optimization
- **API Reference**: 20+ RESTful endpoints for programmatic database and storage operations
- **Docker Integration**: Advanced container lifecycle management, monitoring, and automated cleanup
- **Host Management**: Remote host validation, storage synchronization, and automated resource cleanup

## Support & Community

- **Website**: [stagdb.com](https://stagdb.com/)
- **Issues**: Report bugs and request features via GitHub Issues
- **Community**: Join discussions about database branching and development workflows

## License

StagDB Community Edition is open source software. Check the LICENSE file for details.

---

**Ready to revolutionize your database workflow?** Start with StagDB Community Edition and experience the power of instant database branching. Visit [stagdb.com](https://stagdb.com/) to learn more about our enterprise solutions.
