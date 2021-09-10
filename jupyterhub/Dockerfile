From ignore-me

User SYSTEMROOT
# Copy start_jupyterhub.sh to PV

Run chmod +rx ${HOME}/start_jupyterhub.sh

#copy Jupyterhub_config.py

Run chmod +rx ${HOME}/jupyterhub-config.py

# If there is a need to use custom Authenticator, then a modified version of this step is executed as part f environment provisioning process

RUN cp -V ${JUPYTERHUBGIT}/Hub/ldapauthenticator.py /opt/app-root/lib/python3.6.site-packages/ldapauthenticator

CMD ["/opt/app-root/src/start_jupyterhub.sh"]
