# OAuth2-Proxy: Cluster Application Authentication Provider

## Overview

OAuth2-Proxy is a reverse proxy that provides authentication for your applications by integrating with OAuth2 authentication providers. It allows you to protect your services by adding authentication in front of them. In our case, OAuth2-Proxy has been set up on our Google Kubernetes Engine (GKE) cluster to provide authentication for multiple internal applications.

## How OAuth2-Proxy Works

OAuth2-Proxy acts as an authentication gateway. When a user tries to access an application behind the proxy, the user is redirected to an OAuth2 provider (like Okta, Google, GitHub, etc.) to authenticate. After successful authentication, the user is redirected back to the original application.

OAuth2-Proxy validates the token received from the OAuth2 provider and grants access if the authentication is successful. It can also handle group-based access controls, ensuring that only specific groups have access to certain applications.

## Key Concepts

- **OAuth2 Provider:** An authentication service that issues OAuth2 tokens (e.g., Okta, Google, GitHub).
- **OAuth2-Proxy:** A reverse proxy that intercepts requests, redirects unauthenticated users to the OAuth2 provider, and grants access upon successful authentication.
- **Access Control:** OAuth2-Proxy supports group-based and role-based access control. This allows limiting access to specific users or groups for each application.

## How ingress-nginx Routes Traffic to OAuth2-Proxy

Ingress-nginx acts as the first point of contact for incoming traffic to your applications. Here’s how it integrates with OAuth2-Proxy for authentication:

1. **Routing to OAuth2-Proxy:** When a request is made to a protected application, ingress-nginx first checks if the request is authenticated by inspecting the headers (such as cookies or tokens). If the request is not authenticated, ingress-nginx will route the traffic to the OAuth2-Proxy service.

2. **OAuth2-Proxy Authentication Flow:** OAuth2-Proxy will redirect the user to the configured OAuth2 provider (e.g., Okta, Google) for authentication. Once the user authenticates, the OAuth2 provider redirects the user back to OAuth2-Proxy.

3. **Access Control Check:** OAuth2-Proxy checks the user’s token and validates if the user belongs to the allowed groups defined for the application. If the user is authorized, OAuth2-Proxy will forward the request to the upstream service (the protected application).

4. **Routing to the Upstream Service:** If the authentication and group checks are successful, OAuth2-Proxy will allow ingress-nginx to route the request to the backend service (e.g., Dagster or Uptime). If the authentication fails or the user is not in the allowed group, OAuth2-Proxy will deny the request and return an error, typically a 403 Forbidden.

In short, ingress-nginx acts as a proxy that first sends requests to OAuth2-Proxy for authentication, and based on the result of that authentication, it either forwards the request to the desired application or denies access.

## Setup

### Deploy Helm chart

In the namespace of the application you need to secure, install an instance of Oauth2-proxy by doing a `helm install`.

Example: `helm install oauth2-proxy . -n dagster --values=values.yaml`

This command installs the helm chart in the dagster namespace using the values specified in `values.yaml`

#### Values.yaml

We need to modify a few parts of the values file every time we deploy to a new namespace.

> Note: This command needs to be run in the `k8s_deploy/oauth2-proxy` folder, or replace the . with the full path to the chart.

1. `clientID`, `clientSecret`, `cookieSecret` - update these values with your information from your new Okta OIDC application.
2. `configFile`: Here is an example of same arguments set in the config file for this Oauth2-proxy deployment to protect Dagster:

    ```yaml
    upstreams = [ "https://dagster.roivant.io" ]
        provider = "oidc"
        whitelist_domains = "dagster.roivant.io"
        email_domains = "roivant.com"
        pass_access_token = true
        cookie_domains = ".roivant.io"
        cookie_secure = true
        skip_provider_button = true
        redirect_url = "https://auth.roivant.io/oauth2/callback"
        oidc_issuer_url = "https://roivant.okta.com/oauth2/default"
    ```

    You only need to change where dagster is specified with the URL of the service you are trying to put auth in front of.

3. Everything else in the `values.yaml` can be left as is.
4. Now run your helm install command in the correct namespace with your new values file.

### Apply ingress for Oauth2-proxy in Oauth2-proxy Namespace

We need to give Oauth2-proxy an ingress so the communication can happen between the service and the authentication provider; in our case Okta.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/backend-protocol: HTTP
    nginx.ingress.kubernetes.io/whitelist-source-range: 0.0.0.0/0
  name: oauth2-proxy
spec:
  ingressClassName: nginx
  rules:
    - host: auth.app.roivant.io
      http:
        paths:
          - backend:
              service:
                name: oauth2-proxy
                port:
                  number: 80
            path: /
            pathType: ImplementationSpecific
    - host: auth.roivant.io
      http:
        paths:
          - backend:
              service:
                name: oauth2-proxy
                port:
                  number: 80
            path: /
            pathType: ImplementationSpecific
  tls:
    - hosts:
        - auth.app.roivant.io
        - auth.roivant.io
      secretName: auth.app.roivant.prod-tls
```

Apply the ingress: `kubectl apply -f ingress.yaml -n oauth2-proxy` 

### Modify ingress of the service you are putting authentication in front of

As an example, here is what Dagster's ingress now looks like:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/whitelist-source-range: 3.210.88.52/32, 34.102.42.201/32
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/auth-response-headers: "x-auth-request-user, x-auth-request-email, authorization"
    nginx.ingress.kubernetes.io/auth-signin: "https://auth.roivant.io/oauth2/start?rd=$scheme://$host$request_uri"
    nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.dagster.svc.cluster.local/oauth2/auth"
  name: dagster-ingress
  namespace: dagster
spec:
  rules:
  - host: dagster.app.roivant.io
    http:
      paths:
      - backend:
          service:
            name: dagster-dagster-webserver
            port:
              number: 80
        path: /
        pathType: ImplementationSpecific
  - host: dagster.roivant.io
    http:
      paths:
      - backend:
          service:
            name: oauth2-proxy
            port:
              number: 4180
        path: /oauth2
        pathType: Prefix
      - backend:
          service:
            name: dagster-dagster-webserver
            port:
              number: 80
        path: /
        pathType: Prefix
  tls:
  - hosts:
    - dagster.app.roivant.io
    - dagster.roivant.io
    secretName: dagster.app.roivant.prod-tls
```

> Note: The important changes here are the nginx annotations.

```yaml
nginx.ingress.kubernetes.io/whitelist-source-range: 3.210.88.52/32, 34.102.42.201/32
nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
nginx.ingress.kubernetes.io/auth-response-headers: "x-auth-request-user, x-auth-request-email, authorization"
nginx.ingress.kubernetes.io/auth-signin: "https://auth.roivant.io/oauth2/start?rd=$scheme://$host$request_uri"
nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.dagster.svc.cluster.local/oauth2/auth"
```

The `auth-signin` will stay the same for every ingress but the `auth-url` needs to be modified per ingress. For example this one is `oauth2-proxy.dagster.svc.cluster.local` but in a namespace called `uptime-kuma` the url would be `oauth2-proxy.uptime-kuma.svc.cluster.local`.

Apply the ingress `kubectl apply -f ingress.yaml -n dagster`.

## Conclusion

You should now navigate to your services url like `https://dagster.roivant.io` and you should be redirected to Okta to authenticate. 

By using OAuth2-Proxy and ingress-nginx together, we are able to ensure that authentication happens centrally while also applying fine-grained access control to different applications. Requests are routed through OAuth2-Proxy for authentication, and access is granted or denied based on user authentication and group membership.
