FROM bde2020/spark-master:3.3.0-hadoop3.3
COPY entrypoint.sh /opt/cluster/entrypoint.sh
RUN chmod +x /opt/cluster/entrypoint.sh
ENTRYPOINT ["/opt/cluster/entrypoint.sh"]
CMD ["master"]
