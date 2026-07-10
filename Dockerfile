FROM httpd:2.4
WORKDIR /usr/local/apache2
COPY ./index.html /usr/local/apache2/htdocs/index.html
EXPOSE 80
CMD ["apachectl", "-D", "FOREGROUND"]