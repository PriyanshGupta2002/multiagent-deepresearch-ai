
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    research_list_load: {
      executor: 'constant-vus',
      vus: 10,
      duration: '1m',
    },
  },

  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const ACCESS_TOKEN = __ENV.ACCESS_TOKEN;

export default function () {
  const response = http.get(
    `${BASE_URL}/api/v1/research?page=1&limit=20`,
    {
      headers: {
        Cookie: `access_token=${ACCESS_TOKEN}`,
        Accept: 'application/json',
      },
      tags: {
        endpoint: 'research_list',
      },
    }
  );

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response is not empty': (r) => r.body && r.body.length > 0,
  });

  sleep(1);
}
