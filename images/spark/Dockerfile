FROM bde2020/spark-master:3.3.0-hadoop3.3
COPY images/spark/entrypoint.sh images/common/config-functions.sh /opt/cluster/
RUN chmod +x /opt/cluster/entrypoint.sh
ENTRYPOINT ["/opt/cluster/entrypoint.sh"]
CMD ["master"]
