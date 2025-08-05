"""
Django management command for storage configuration synchronization
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.storage_monitor import StorageConfigurationSyncManager
import json


class Command(BaseCommand):
    help = 'Synchronize storage configurations with actual infrastructure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--monitor',
            action='store_true',
            help='Run continuous monitoring mode',
        )
        parser.add_argument(
            '--reconcile',
            action='store_true',
            help='Run reality reconciliation only',
        )
        parser.add_argument(
            '--health-check',
            action='store_true',
            help='Run health check only',
        )
        parser.add_argument(
            '--drift-detection',
            action='store_true',
            help='Run drift detection only',
        )
        parser.add_argument(
            '--auto-remediate',
            action='store_true',
            help='Run automatic remediation',
        )
        parser.add_argument(
            '--full-sync',
            action='store_true',
            help='Run full synchronization cycle (default)',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=300,
            help='Monitoring interval in seconds (default: 300)',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output results in JSON format',
        )

    def handle(self, *args, **options):
        sync_manager = StorageConfigurationSyncManager()
        
        if options['monitor']:
            self.run_continuous_monitoring(sync_manager, options['interval'])
        elif options['reconcile']:
            results = sync_manager.monitor.reconcile_with_reality()
            self.output_results('Reality Reconciliation', results, options['json'])
        elif options['health_check']:
            results = sync_manager.monitor.monitor_storage_health()
            self.output_results('Health Check', results, options['json'])
        elif options['drift_detection']:
            results = sync_manager.monitor.detect_configuration_drift()
            self.output_results('Drift Detection', results, options['json'])
        elif options['auto_remediate']:
            results = sync_manager.monitor.auto_remediate_issues()
            self.output_results('Auto Remediation', results, options['json'])
        else:
            # Default: full sync
            results = sync_manager.run_full_sync_cycle()
            self.output_results('Full Sync', results, options['json'])

    def run_continuous_monitoring(self, sync_manager, interval):
        """Run continuous monitoring mode"""
        self.stdout.write(
            self.style.SUCCESS(f'Starting continuous monitoring (interval: {interval}s)')
        )
        
        import time
        try:
            while True:
                self.stdout.write(f'\n--- Sync Cycle: {timezone.now()} ---')
                
                results = sync_manager.run_full_sync_cycle()
                self.output_results('Monitoring Cycle', results, json_format=False)
                
                self.stdout.write(f'Sleeping for {interval} seconds...')
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\nMonitoring stopped by user'))

    def output_results(self, operation_name, results, json_format=False):
        """Output results in either JSON or human-readable format"""
        if json_format:
            self.stdout.write(json.dumps(results, indent=2, default=str))
        else:
            self.stdout.write(self.style.SUCCESS(f'\n=== {operation_name} Results ==='))
            self.format_human_readable_results(results)

    def format_human_readable_results(self, results):
        """Format results in human-readable format"""
        if 'health_monitoring' in results:
            health = results['health_monitoring']
            self.stdout.write(f'\n📊 Health Monitoring:')
            if health.get('healthy'):
                self.stdout.write(self.style.SUCCESS(f'  ✅ Healthy: {", ".join(health["healthy"])}'))
            if health.get('degraded'):
                self.stdout.write(self.style.WARNING(f'  ⚠️  Degraded: {len(health["degraded"])} configurations'))
                for item in health['degraded']:
                    self.stdout.write(f'     - {item["name"]}: {", ".join(item["issues"])}')
            if health.get('failed'):
                self.stdout.write(self.style.ERROR(f'  ❌ Failed: {len(health["failed"])} configurations'))
                for item in health['failed']:
                    self.stdout.write(f'     - {item["name"]}: {item["error"]}')
            if health.get('missing'):
                self.stdout.write(self.style.ERROR(f'  🚫 Missing: {", ".join(health["missing"])}'))

        if 'reality_reconciliation' in results:
            recon = results['reality_reconciliation']
            self.stdout.write(f'\n🔄 Reality Reconciliation:')
            if recon.get('reconciled'):
                self.stdout.write(self.style.SUCCESS(f'  ✅ Reconciled: {len(recon["reconciled"])} configurations'))
            if recon.get('orphaned_pools'):
                self.stdout.write(self.style.WARNING(f'  🏝️  Orphaned Pools: {len(recon["orphaned_pools"])}'))
                for pool in recon['orphaned_pools']:
                    self.stdout.write(f'     - {pool["name"]} ({pool["size"]}, {pool["health"]})')
            if recon.get('missing_pools'):
                self.stdout.write(self.style.ERROR(f'  🕳️  Missing Pools: {len(recon["missing_pools"])}'))
                for pool in recon['missing_pools']:
                    self.stdout.write(f'     - {pool["name"]} (config: {pool["config_name"]})')

        if 'drift_detection' in results:
            drift = results['drift_detection']
            self.stdout.write(f'\n🎯 Drift Detection:')
            if drift.get('no_drift'):
                self.stdout.write(self.style.SUCCESS(f'  ✅ No Drift: {", ".join(drift["no_drift"])}'))
            if drift.get('minor_drift'):
                self.stdout.write(self.style.WARNING(f'  📊 Minor Drift: {len(drift["minor_drift"])} configurations'))
            if drift.get('major_drift'):
                self.stdout.write(self.style.ERROR(f'  🚨 Major Drift: {len(drift["major_drift"])} configurations'))
                for item in drift['major_drift']:
                    self.stdout.write(f'     - {item["config"]}: {item["recommended_action"]}')

        if 'auto_remediation' in results:
            remediation = results['auto_remediation']
            self.stdout.write(f'\n🔧 Auto Remediation:')
            if remediation.get('remediated'):
                self.stdout.write(self.style.SUCCESS(f'  ✅ Remediated: {len(remediation["remediated"])} issues'))
                for item in remediation['remediated']:
                    self.stdout.write(f'     - {item["config"]}: {item["action"]}')
            if remediation.get('manual_intervention_required'):
                self.stdout.write(self.style.WARNING(f'  👤 Manual Intervention: {len(remediation["manual_intervention_required"])} issues'))
                for item in remediation['manual_intervention_required']:
                    self.stdout.write(f'     - {item["config"]}: {item["suggested_action"]}')
            if remediation.get('failed_remediation'):
                self.stdout.write(self.style.ERROR(f'  ❌ Failed Remediation: {len(remediation["failed_remediation"])} issues'))

        if 'timestamp' in results:
            self.stdout.write(f'\n⏰ Completed at: {results["timestamp"]}')