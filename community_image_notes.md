In order to deploy Open Source version of Jupyterhub on Microsoft Azure with Red Hat Openshift Implementation of Kubernetes.
Redhat Openshift and Kubernetes are both container orchestration softwares but open shift has been packaged as downstream open source platform. In simple works Openshift is a packaging of
Kubernetes with additional security and productivity features.

# How do Red Hat OpenShift and Kubernetes work?
Red Hat OpenShift and Kubernetes both manage groups of containers called clusters. Each cluster has 2 parts: a control plane and worker nodes. Containers run in the worker nodes,
each of which has its own Linux operating system. The control plane maintains the cluster’s overall state (like what apps are running and which container images are used), 
while worker nodes do the actual computing work.

# What are the components of a Kubernetes cluster?
A working Kubernetes deployment is called a cluster. You can visualize a Kubernetes cluster as two parts: the control plane and the compute machines, or nodes. Each node is its own Linux® environment, and could be either a physical or virtual machine. Each node runs pods, which are made up of containers.

This diagram shows how the parts of a Kubernetes cluster relate to one another:
