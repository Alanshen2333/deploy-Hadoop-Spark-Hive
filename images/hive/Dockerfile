FROM curlimages/curl:8.10.1 AS jdbc
WORKDIR /tmp
RUN curl --fail --location --retry 3 https://jdbc.postgresql.org/download/postgresql-42.7.4.jar -o postgresql.jar \
    && echo '188976721ead8e8627eb6d8389d500dccc0c9bebd885268a3047180274a6031e  postgresql.jar' | sha256sum -c -

FROM bde2020/hive:2.3.2
# Remove the bundled JDBC driver to avoid ambiguous class loading.
RUN rm -f /opt/hive/lib/postgresql*.jar
COPY --from=jdbc /tmp/postgresql.jar /opt/hive/lib/postgresql-42.7.4.jar
COPY images/hive/entrypoint.sh images/hive/start.sh images/common/config-functions.sh /opt/cluster/
RUN chmod +x /opt/cluster/*.sh
ENTRYPOINT ["/opt/cluster/entrypoint.sh"]
CMD ["server"]
