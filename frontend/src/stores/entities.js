import {nodesAPI,scenariosAPI,drillsAPI} from '../api/entities.js';
export const store={nodes:[],scenarios:[],drills:[],async refresh(){[this.nodes,this.scenarios,this.drills]=await Promise.all([nodesAPI.list(),scenariosAPI.list(),drillsAPI.list()]);}};
