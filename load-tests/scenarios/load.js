import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const ACCESS_TOKEN = __ENV.ACCESS_TOKEN;

const VUS = Number(__ENV.VUS || 10);
const DURATION = __ENV.DURATION || '1m';
const RAMP_UP = Number(__ENV.RAMP_UP || 30);
const RAMP_DOWN = Number(__ENV.RAMP_DOWN || 15);
const THINK_TIME = Number(__ENV.THINK_TIME || 1);

export const options = {
  scenarios: {
    research_list: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: `${RAMP_UP}s`, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: `${RAMP_DOWN}s`, target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const response = http.get(
    `${BASE_URL}/api/v1/research?page=1&limit=20`,
    {
      headers: {
        Cookie: `access_token=${ACCESS_TOKEN}`,
        Accept: 'application/json',
      },
      tags: { endpoint: 'research_list' },
    }
  );
  if (response.status !== 200) {
  console.log(
    `Failed request: status=${response.status}, body=${response.body}`
  );
}

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response is not empty': (r) => r.body && r.body.length > 0,
  });

  if (THINK_TIME > 0) {
    sleep(THINK_TIME);
  }
}
