#!/bin/bash
# Hive startup wrapper: init metastore schema (if needed), then start HiveServer2

schematool -dbType postgres -initSchema || true
exec startup.sh
