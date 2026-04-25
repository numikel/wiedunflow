# Test_deep

## Company

**Name:** Acme Corp  
**Founded:** 2010

### Address

**Street:** ul. Marszałkowska 1  
**City:** Warszawa

#### Geo

**Lat:** 52.2297  
**Lng:** 21.0122  
**Verified:** true

### Departments

| name | size | remote |
| --- | --- | --- |
| Engineering | 40 | true |
| Marketing | 15 | false |
| Finance | 10 | false |

## Servers

| name | tags | config |
| --- | --- | --- |
| web1 | http, nginx | port: 80; ssl: false |
| web2 | https, nginx | port: 443; ssl: true |

## Pipeline

**Stages:** build, test, deploy

### Notifications

**Slack:** #dev-alerts  
**Email:** devops@acme.com, cto@acme.com

### Retry

**Max_attempts:** 3

#### Backoff

**Strategy:** exponential  
**Base_seconds:** 5  
**Max_seconds:** 60
